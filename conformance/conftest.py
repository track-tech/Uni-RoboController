# Copyright (c) 2026-2027 zbc
"""CTS 测试夹具：启动参考服务端、准备秘密与端口。"""

from __future__ import annotations

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
    def __init__(self, proc: subprocess.Popen, secret: bytes, addr, discovery: int):
        self.proc = proc
        self.secret = secret
        self.addr = addr
        self.discovery = discovery

    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _start(tmp_path: Path, camera: bool) -> ServerHandle:
    secret = os.urandom(32)
    secret_file = tmp_path / "secret.bin"
    secret_file.write_bytes(secret)
    ctrl = free_port()
    disc = free_port()
    cmd = [
        sys.executable, str(ROOT / "tools" / "codec_ref" / "ref_server.py"),
        "--ctrl-port", str(ctrl), "--discovery-port", str(disc),
        "--secret-file", str(secret_file),
    ]
    if not camera:
        cmd.append("--no-camera")
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    if not _wait_discovery(disc):
        proc.kill()
        raise RuntimeError("reference server did not start")
    return ServerHandle(proc, secret, ("127.0.0.1", ctrl), disc)


@pytest.fixture
def server(tmp_path):
    handle = _start(tmp_path, camera=False)
    yield handle
    handle.stop()


@pytest.fixture
def video_server(tmp_path):
    handle = _start(tmp_path, camera=True)
    yield handle
    handle.stop()


def pytest_configure(config):
    config.addinivalue_line("markers", "dynamic: 需要运行参考服务端的动态 CTS")
    config.addinivalue_line("markers", "static: 静态校验，不启动服务端")
