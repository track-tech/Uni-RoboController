# Copyright (c) 2026-2027 zbc
"""CTS 动态组：发现、配对、控制、遥测、安全、视频与模型状态。"""

from __future__ import annotations

import os
import socket
import time

import pytest

from cts.client import UrcClient, UrcError, VideoAssembler
from urc_ref import capability, crypto, frame, messages


def _client(server) -> UrcClient:
    c = UrcClient(server.secret, server.addr)
    c.connect()
    return c


def _telem(c: UrcClient, timeout: float = 2.0) -> messages.Telemetry:
    f = c.recv_type(frame.T_TELEM, timeout=timeout)
    return messages.unpack_telem(f.payload)


def _event_code(c: UrcClient, want: int, timeout: float = 2.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = c.recv_type(frame.T_EVENT, timeout=end - time.monotonic())
        if messages.unpack_event(f.payload)["code"] == want:
            return
    raise AssertionError(f"event 0x{want:04x} not received")


@pytest.mark.dynamic
def test_discovery(server):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    sock.sendto(messages.pack_discover(b"1234567890abcdef", b"cts-probe-000001"),
                ("127.0.0.1", server.discovery))
    data, _ = sock.recvfrom(2048)
    ann = messages.unpack_announce(data)
    assert ann.robot_id == "mock-quadruped"
    assert ann.ctrl_port == server.addr[1]
    sock.close()


@pytest.mark.dynamic
def test_connect_and_caps(server):
    c = UrcClient(server.secret, server.addr)
    ack = c.connect()
    assert ack.robot_id == "mock-quadruped"
    assert c.caps["schema"] == "urc-capability/v1"
    assert c.caps["control"]["modes"][0]["interface"] == "velocity"
    c.close()


@pytest.mark.dynamic
def test_control_and_telemetry(server):
    c = _client(server)
    for _ in range(30):
        c.send_ctrl([16384, 0, 0, 0], [0], flags=1)
        time.sleep(0.01)
    t = _telem(c)
    assert t.x > 0.5, t
    assert t.remote_age_ms < 200
    # 死手释放 -> 零速
    c.send_ctrl([0, 0, 0, 0], [0], flags=0)
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        t = _telem(c)
        if abs(t.x) < 1e-3:
            break
    assert abs(t.x) < 1e-3, t
    c.close()


@pytest.mark.dynamic
def test_auth_failure_and_lockout(server):
    c = UrcClient(server.secret, server.addr)
    c.hello()
    for _ in range(5):
        proof = crypto.auth_proof(os.urandom(32), c.app_nonce, c.robot_nonce, c.session_id)
        c._send(frame.T_AUTH, messages.pack_auth(proof, b"cts-client-00001", "cts"), encrypt=False)
        with pytest.raises(UrcError) as exc:
            c.recv(timeout=1.0)
        assert exc.value.code == 0x0101
    # 第 6 次即使正确也处于锁定
    proof = crypto.auth_proof(server.secret, c.app_nonce, c.robot_nonce, c.session_id)
    c._send(frame.T_AUTH, messages.pack_auth(proof, b"cts-client-00001", "cts"), encrypt=False)
    with pytest.raises(UrcError) as exc:
        c.recv(timeout=1.0)
    assert exc.value.code == 0x0602
    c.close()


@pytest.mark.dynamic
def test_single_controller(server):
    c1 = _client(server)
    c2 = UrcClient(server.secret, server.addr)
    with pytest.raises(UrcError) as exc:
        c2.hello()
    assert exc.value.code == 0x0103
    c1.close()
    c2.close()


@pytest.mark.dynamic
def test_estop_latch_and_release(server):
    c = _client(server)
    c.send_estop(1)
    _event_code(c, 0x0001)
    # 急停锁存中：控制不生效
    c.send_ctrl([16384, 0, 0, 0], [0], flags=1)
    t = _telem(c)
    assert abs(t.x) < 1e-3 and (t.fault_flags & 2), t
    # 显式复位
    c.send_session_ctrl(4)
    time.sleep(0.05)
    for _ in range(20):
        c.send_ctrl([16384, 0, 0, 0], [0], flags=1)
        time.sleep(0.01)
    t = _telem(c)
    assert t.x > 0.5, t
    c.close()


@pytest.mark.dynamic
def test_watchdog(server):
    c = _client(server)
    c.send_ctrl([16384, 0, 0, 0], [0], flags=1)
    deadline = time.monotonic() + 1.5
    fired = False
    while time.monotonic() < deadline:
        t = _telem(c, timeout=1.0)
        if t.fault_flags & 1:
            fired = True
            break
    assert fired, "watchdog did not fire"
    c.close()


@pytest.mark.dynamic
def test_tampered_packet_ignored(server):
    c = _client(server)
    c.send_ctrl([16384, 0, 0, 0], [0], flags=1)
    raw = bytearray(frame.pack(
        frame.Frame(frame.T_CTRL, messages.pack_ctrl(0, [32767, 0, 0, 0], [0], 1),
                    session_id=c.session_id, seq=c.tx_seq + 1, ts_us=time.monotonic_ns() // 1000),
        c.ctx, to_robot=True))
    raw[-1] ^= 0xFF
    c.sock.sendto(bytes(raw), server.addr)
    for _ in range(20):
        c.send_ctrl([16384, 0, 0, 0], [0], flags=1)
        time.sleep(0.01)
    t = _telem(c)
    assert t.x > 0.5, t
    c.close()


@pytest.mark.dynamic
def test_model_state(server):
    c = _client(server)
    f = c.recv_type(frame.T_MODEL_STATE, timeout=2.0)
    state = messages.unpack_model_state(f.payload)
    assert state["joint_count"] == 16
    order = c.caps["model"]["joint_order"]
    assert state["joint_order_hash"] == capability.joint_order_hash(order)
    c.close()


@pytest.mark.dynamic
def test_video_frame(video_server):
    c = _client(video_server)
    assembler = VideoAssembler()
    deadline = time.monotonic() + 5.0
    result = None
    while time.monotonic() < deadline:
        f = c.recv(timeout=1.0)
        if f is None or f.type != frame.T_VIDEO:
            continue
        result = assembler.add(f.payload)
        if result is not None:
            break
    assert result is not None, "video frame not assembled"
    meta, data = result
    assert meta["frame_bytes"] == len(data)
    assert len(data) == 160 * 120 * 3
    assert meta["media_flags"] & 0x04
    c.close()
