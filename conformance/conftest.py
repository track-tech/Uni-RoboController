# Copyright (c) 2026-2027 zbc
"""CTS 测试夹具与报告。

内容：
    启动 Python 参考服务端或 C++ mock（每用例独立进程/随机端口），
    支持外部 target 环境变量、统计文件、pytest cts_id marker 与 cts-report.json。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "codec_ref"))
sys.path.insert(0, str(ROOT / "conformance"))

from urc_ref import messages  # noqa: E402

REPORT: dict[str, dict] = {}
ITEMS: dict[str, str] = {}
CFG: dict[str, object] = {}


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_discovery(port: int, timeout: float = 5.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    probe = messages.pack_discover(os.urandom(16), b"cts-probe-000001")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            sock.sendto(probe, ("127.0.0.1", port))
            sock.recvfrom(2048)
            sock.close()
            return True
        except (socket.timeout, ConnectionResetError, OSError):
            continue
    sock.close()
    return False


class ServerHandle:
    def __init__(self, proc: subprocess.Popen | None, secret: bytes, addr, discovery: int,
                 stats_file: str | None = None):
        self.proc = proc
        self.secret = secret
        self.addr = addr
        self.discovery = discovery
        self.stats_file = stats_file

    def stop(self) -> None:
        if not self.proc:
            return
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=5)

    def stats(self) -> dict:
        if not self.stats_file or not Path(self.stats_file).exists():
            return {}
        for _ in range(20):
            try:
                return json.loads(Path(self.stats_file).read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                time.sleep(0.02)
        return {}


def _secret(tmp_path: Path) -> tuple[bytes, Path]:
    secret = os.urandom(32)
    path = tmp_path / "urc.secret"
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret, path


def _start(tmp_path: Path, extra_args: list[str] | None = None, camera: bool = False) -> ServerHandle:
    extra = list(extra_args or [])
    secret, secret_file = _secret(tmp_path)
    ctrl, disc = free_port(), free_port()
    stats_file = str(tmp_path / "stats.json")
    capability = str(ROOT / "protocol" / "examples" / "capability.mock_quadruped.json")

    if os.environ.get("URC_CTS_MOCK_BIN"):
        mock_stats = stats_file
        if os.name == "nt":
            # MSYS/C++ mock 写绝对 Windows 路径会失败；改用仓库内相对路径
            local = ROOT / ".cts-tmp"
            local.mkdir(exist_ok=True)
            stats_file = str(local / f"{os.getpid()}-{time.time_ns()}.json")
            mock_stats = os.path.relpath(stats_file, ROOT)
        cmd = [os.environ["URC_CTS_MOCK_BIN"], "--bind", "127.0.0.1",
               "--ctrl-port", str(ctrl), "--discovery-port", str(disc),
               "--capability", capability, "--secret-file", str(secret_file),
               "--stats-file", mock_stats]
        if not camera:
            cmd.append("--no-camera")
        cmd += extra
    else:
        cmd = [sys.executable, str(ROOT / "tools/codec_ref/ref_server.py"),
               "--bind", "127.0.0.1", "--ctrl-port", str(ctrl), "--discovery-port", str(disc),
               "--capability", capability, "--secret-file", str(secret_file),
               "--stats-file", stats_file]
        if not camera:
            cmd.append("--no-camera")
        cmd += extra
    proc = subprocess.Popen(cmd, stdout=None if os.environ.get("URC_CTS_DEBUG") else subprocess.DEVNULL,
                            stderr=None if os.environ.get("URC_CTS_DEBUG") else subprocess.STDOUT)
    if not _wait_discovery(disc):
        proc.kill()
        raise RuntimeError(f"server did not start: {' '.join(cmd)}")
    return ServerHandle(proc, secret, ("127.0.0.1", ctrl), disc, stats_file)


def _external() -> ServerHandle:
    target = os.environ.get("URC_CTS_TARGET")
    with open(os.environ["URC_CTS_SECRET_FILE"], "rb") as f:
        secret = f.read()
    host, port = target.rsplit(":", 1)
    disc = int(os.environ.get("URC_CTS_DISCOVERY", "0"))
    return ServerHandle(None, secret, (host, int(port)), disc,
                        os.environ.get("URC_CTS_STATS_FILE"))


@pytest.fixture
def make_server(tmp_path):
    handles: list[ServerHandle] = []

    def start(extra: list[str] | None = None, camera: bool = False) -> ServerHandle:
        if os.environ.get("URC_CTS_REQUIRE_EXTERNAL") == "1" and not (
                os.environ.get("URC_CTS_MOCK_BIN") or os.environ.get("URC_CTS_TARGET")):
            pytest.fail("URC_CTS_REQUIRE_EXTERNAL=1 but neither MOCK_BIN nor TARGET is set")
        if os.environ.get("URC_CTS_TARGET"):
            handle = _external()
        else:
            handle = _start(tmp_path, extra, camera)
        handles.append(handle)
        return handle

    yield start
    for handle in handles:
        handle.stop()


@pytest.fixture
def server(make_server):
    return make_server()


@pytest.fixture
def video_server(make_server):
    return make_server(camera=True)


# ---------- report ----------

def pytest_addoption(parser):
    parser.addoption("--allow-motion", action="store_true", default=False,
                     help="allow tests that may move a real robot (mock/rig only)")


def pytest_configure(config):
    config.addinivalue_line("markers", "dynamic: 需要运行服务端的动态 CTS")
    config.addinivalue_line("markers", "static: 静态校验，不启动服务端")
    config.addinivalue_line("markers", "cts_id(id): CTS 用例 ID（写入报告）")
    config.addinivalue_line("markers", "mock_only: 仅对 mock 运行（需要注入参数）")
    CFG["allow_motion"] = config.getoption("--allow-motion")


def pytest_collection_modifyitems(config, items):
    for item in items:
        marker = item.get_closest_marker("cts_id")
        if marker:
            ITEMS[item.nodeid] = marker.args[0]


def pytest_runtest_logreport(report):
    if not report.when == "call" and not (report.when == "setup" and report.skipped):
        return
    entry = REPORT.setdefault(report.nodeid, {"status": "passed", "detail": ""})
    if report.failed:
        entry["status"] = "failed"
        entry["detail"] = str(report.longrepr)[-500:]
    elif report.skipped:
        if hasattr(report, "wasxfail"):
            entry["status"] = "xfail"
        else:
            entry["status"] = "skipped"


def pytest_sessionfinish(session, exitstatus):
    cases = []
    for nodeid, cts_id in sorted(ITEMS.items(), key=lambda kv: kv[1]):
        result = REPORT.get(nodeid, {"status": "skipped"})
        cases.append({"id": cts_id, "status": result["status"],
                      "duration_ms": 0, "detail": result.get("detail", "")})
    summary = {k: sum(1 for c in cases if c["status"] == k)
               for k in ("passed", "failed", "skipped", "xfail")}
    payload = {"schema": "urc-cts-report/v1", "suite": "dynamic",
               "target": os.environ.get("URC_CTS_TARGET", "ref-server"),
               "started_at": str(session.startpath), "cases": cases, "summary": summary}
    out = os.environ.get("URC_CTS_REPORT")
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
