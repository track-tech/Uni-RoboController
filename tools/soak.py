# Copyright (c) 2026-2027 zbc
"""30 分钟浸泡测试：启动 mock/参考服务端，持续控制并采样 RSS/fd/stats。

用法：
    python tools/soak.py --bin agent/build/mock_robot --duration 1800 --drop 5 --rate 100
    python tools/soak.py --ref tools/codec_ref/ref_server.py --duration 60 --rate 100
"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "codec_ref"))
sys.path.insert(0, str(ROOT / "conformance"))

from cts.client import UrcClient, UrcError  # noqa: E402
from urc_ref import messages  # noqa: E402


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_discovery(port: int, timeout: float = 5.0) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(0.2)
    probe = messages.pack_discover(os.urandom(16), b"soak-probe-00001")
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            sock.sendto(probe, ("127.0.0.1", port))
            sock.recvfrom(2048)
            sock.close()
            return True
        except OSError:
            continue
    sock.close()
    return False


def proc_metrics(pid: int) -> tuple[int, int]:
    rss_kb, fds = 0, 0
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
        fds = len(list(Path(f"/proc/{pid}/fd").iterdir()))
    except OSError:
        pass
    return rss_kb, fds


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", default=None, help="C++ mock_robot 路径")
    parser.add_argument("--ref", default=None, help="Python ref_server.py 路径（本地）")
    parser.add_argument("--duration", type=int, default=1800)
    parser.add_argument("--rate", type=int, default=100)
    parser.add_argument("--drop", type=float, default=5.0)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--secret-file", default=os.path.join(tempfile.gettempdir(), "urc-soak.secret"))
    parser.add_argument("--stats-file", default=os.path.join(tempfile.gettempdir(), "urc-soak-stats.json"))
    parser.add_argument("--report", default="artifacts/soak-report.json")
    args = parser.parse_args()
    if not args.bin and not args.ref:
        raise SystemExit("either --bin or --ref required")
    ctrl, disc = free_port(), free_port()
    secret = os.urandom(32)
    Path(args.secret_file).write_bytes(secret)
    cmd = [args.bin] if args.bin else [sys.executable, args.ref]
    cmd += ["--bind", "127.0.0.1", "--ctrl-port", str(ctrl), "--discovery-port", str(disc),
            "--secret-file", args.secret_file, "--no-camera",
            "--drop", str(args.drop), "--seed", str(args.seed),
            "--stats-file", args.stats_file]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if not wait_discovery(disc):
        proc.kill()
        raise SystemExit("server did not start")
    client = None
    for _ in range(20):
        try:
            client = UrcClient(secret, ("127.0.0.1", ctrl))
            client.connect()
            break
        except (TimeoutError, UrcError, OSError):
            time.sleep(0.1)
    if client is None:
        proc.kill()
        raise SystemExit("client could not connect")
    baseline = None
    start = time.monotonic()
    interval = 1.0 / max(1, args.rate)
    last_report = 0
    try:
        while time.monotonic() - start < args.duration:
            try:
                client.send_ctrl([8000, 0, 0, 0])
            except OSError:
                pass
            client.recv(timeout=0.001)
            if time.monotonic() - last_report > 30:
                last_report = time.monotonic()
                rss, fds = proc_metrics(proc.pid)
                elapsed = int(time.monotonic() - start)
                print(f"[soak] t={elapsed}s rss={rss}KB fds={fds}", flush=True)
                if baseline is None and elapsed >= 60:
                    baseline = (rss, fds)
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    elapsed = time.monotonic() - start
    proc.send_signal(signal.SIGTERM)
    try:
        code = proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        code = proc.wait(timeout=5)
    rss, fds = proc_metrics(proc.pid)
    stats = {}
    try:
        import json
        stats = json.loads(Path(args.stats_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    report = {"duration_s": round(elapsed, 1), "exit_code": code, "rss_kb": rss, "fds": fds,
              "baseline": baseline, "stats": stats}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[soak] done exit={code} report={args.report}", flush=True)
    if args.bin and code != 0:
        print("[soak] FAIL: mock did not exit 0 on SIGTERM", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
