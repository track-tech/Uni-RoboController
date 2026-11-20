# Copyright (c) 2026-2027 zbc
"""URC 协议一致性动态 CTS（P0 矩阵 + 关键 P1）。

覆盖 18 §6.2 的 P0：发现、配对、认证门、会话、单控制者、控制/TTL/越界、
看门狗、急停两步复位、重放/篡改、跨架构由 arch job 单独报告。
"""

from __future__ import annotations

import json
import os
import socket
import struct
import time

import pytest

from cts.client import UrcClient, UrcError, VideoAssembler
from urc_ref import capability as capmod
from urc_ref import crypto, frame, messages
from urc_ref.crc import crc32c_final

pytestmark = pytest.mark.dynamic

EVT_ESTOP_ACKED, EVT_WATCHDOG, EVT_ARMED, EVT_SESSION_EXPIRED, EVT_ESTOP_RELEASED = (
    0x0001, 0x0002, 0x0003, 0x0004, 0x0005)
ERR_AUTH, ERR_ROLE, ERR_RANGE, ERR_ESTOP, ERR_LOCKED = 0x0101, 0x0103, 0x0301, 0x0302, 0x0602


# ---------- helpers ----------

def _client(server, secret: bytes | None = None) -> UrcClient:
    return UrcClient(secret or server.secret, server.addr)


def _telem(client: UrcClient, timeout: float = 2.0):
    f = client.recv_type(frame.T_TELEM, timeout=timeout)
    return messages.unpack_telem(f.payload)


def _wait_telem(client: UrcClient, pred, timeout: float = 2.0):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = _telem(client, timeout=end - time.monotonic())
        if pred(last):
            return last
    raise AssertionError(f"telemetry predicate not met: {last}")


def _wait_stats(server, key: str, count: int = 1, timeout: float = 2.0) -> dict:
    end = time.monotonic() + timeout
    stats = {}
    while time.monotonic() < end:
        stats = server.stats()
        if stats.get(key, 0) >= count:
            return stats
        time.sleep(0.03)
    return stats


def _recv_event(client: UrcClient, code: int, timeout: float = 2.0) -> messages.unpack_event:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = client.recv(timeout=end - time.monotonic())
        if f is None:
            break
        if f.type == frame.T_EVENT:
            ev = messages.unpack_event(f.payload)
            if ev["code"] == code:
                return ev
        if f.type == frame.T_ERROR:
            err = messages.unpack_error(f.payload)
            raise UrcError(err["code"], err["message"])
    raise TimeoutError(f"event 0x{code:04x} not received")


def _expect_error(client: UrcClient, code: int, timeout: float = 2.0) -> UrcError:
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        try:
            f = client.recv(timeout=end - time.monotonic())
        except UrcError as exc:
            if exc.code == code:
                return exc
            last = exc
            continue
        if f is None:
            break
    raise AssertionError(f"expected error 0x{code:04x}, got {last}")


def _raw_send(server, ftype: int, payload: bytes = b"", stream: int = frame.S_CTRL,
              session_id: int = 0, seq: int = 1) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        f = frame.Frame(ftype, payload, stream=stream, session_id=session_id, seq=seq, ts_us=1)
        sock.sendto(frame.pack(f), server.addr)
    finally:
        sock.close()


def _tampered(raw: bytes) -> bytes:
    body = bytearray(raw[32:])
    body[0] ^= 0xFF
    header = bytearray(raw[:32])
    header[28:32] = b"\x00\x00\x00\x00"
    header[28:32] = struct.pack("<I", crc32c_final(bytes(header) + bytes(body)))
    return bytes(header) + bytes(body)


# ---------- 硬编码线上契约（与参考编解码实现独立） ----------

def test_wire_contract_hardcoded():
    assert messages.pack_session_ctrl(3).hex() == "03000000"
    assert messages.pack_session_ctrl(4).hex() == "04000000"
    assert messages.pack_event(0x0001, 0, "").hex() == "01000000"
    assert messages.pack_error(0x0101, "").hex() == "010100"
    assert len(messages.pack_feedback(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)) == 36
    assert frame.Frame(0x17, b"\x00\x00\x00\x00").payload == b"\x00\x00\x00\x00"


def test_hello_ack_rate_limited(server):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    sock.settimeout(0.05)
    hello = messages.pack_hello(1, 0, 0, 0, b"cts-client-00001", os.urandom(16), "cts")
    raw = frame.pack(frame.Frame(frame.T_HELLO, hello, session_id=0, seq=1, ts_us=1))
    for _ in range(30):
        sock.sendto(raw, server.addr)
    acks = 0
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        try:
            data, _ = sock.recvfrom(2048)
        except socket.timeout:
            continue
        if len(data) > 5 and data[5] == frame.T_HELLO_ACK:
            acks += 1
    sock.close()
    assert acks <= 12, f"HELLO_ACK rate limit broken: {acks}"


# ---------- 发现 / 配对 ----------

@pytest.mark.cts_id("CTS-D-01")
def test_discovery_announce(server):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        probe = messages.pack_discover(os.urandom(16), b"cts-probe-000001")
        sock.sendto(probe, ("127.0.0.1", server.discovery))
        data, _ = sock.recvfrom(2048)
    finally:
        sock.close()
    ann = messages.unpack_announce(data)
    assert ann.robot_id
    assert ann.ctrl_port == server.addr[1]
    assert ann.video_port == 0 and ann.depth_port == 0 and ann.map_port == 0
    assert server.secret not in data
    client = _client(server)
    client.connect()
    assert ann.caps_hash == capmod.caps_hash(client.caps)
    client.close()


@pytest.mark.cts_id("CTS-P-01")
def test_auth_lockout_per_source(server):
    client = _client(server)
    client.hello()
    wrong = os.urandom(32)
    for _ in range(5):
        proof = crypto.auth_proof(wrong, client.app_nonce, client.robot_nonce, client.session_id)
        client._send(frame.T_AUTH, messages.pack_auth(proof, b"cts-client-00001", "cts"), encrypt=False)
        with pytest.raises(UrcError) as exc:
            client.recv()
        assert exc.value.code == ERR_AUTH
    proof = crypto.auth_proof(server.secret, client.app_nonce, client.robot_nonce, client.session_id)
    client._send(frame.T_AUTH, messages.pack_auth(proof, b"cts-client-00001", "cts"), encrypt=False)
    with pytest.raises(UrcError) as exc:
        client.recv()
    assert exc.value.code == ERR_LOCKED
    assert _wait_stats(server, "auth_fail", 5).get("auth_fail", 0) >= 5
    # 锁定按来源隔离：另一个源端口仍可认证
    other = UrcClient(server.secret, server.addr)
    other.hello()
    other.auth()
    other.close()
    client.close()


@pytest.mark.cts_id("CTS-P-02")
def test_unauthenticated_control_rejected(server):
    for idx, (ftype, payload) in enumerate([
        (frame.T_SESSION_CTRL, messages.pack_session_ctrl(0)),
        (frame.T_SESSION_CTRL, messages.pack_session_ctrl(3)),
        (frame.T_SESSION_CTRL, messages.pack_session_ctrl(4)),
        (frame.T_CTRL, messages.pack_ctrl(0, [16384, 0, 0, 0], [0], 1)),
        (frame.T_ESTOP, messages.pack_estop(1, 1)),
        (frame.T_PING, struct.pack("<Q", 1)),
        (frame.T_AUTH, messages.pack_auth(os.urandom(32), b"cts-client-00001", "cts")),
    ]):
        _raw_send(server, ftype, payload, seq=idx + 1)
        time.sleep(0.01)
    stats = _wait_stats(server, "gate_drop", 6)
    assert stats.get("gate_drop", 0) >= 6
    assert stats.get("estop", 0) == 0
    client = _client(server)
    client.connect()
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    client.close()


# ---------- 会话 / 单控制者 ----------

@pytest.mark.cts_id("CTS-S-01")
def test_single_controller(server):
    c1 = _client(server)
    c1.connect()
    c2 = _client(server)
    with pytest.raises(UrcError) as exc:
        c2.hello()
    assert exc.value.code == ERR_ROLE
    c1.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(c1, lambda t: t.x > 0.5).x > 0.5
    c1.close()
    c2.close()


@pytest.mark.cts_id("CTS-S-02")
def test_session_timeout_and_estop_latch(make_server):
    server = make_server(["--session-timeout-ms", "500"])
    c1 = _client(server)
    c1.connect()
    c1.send_estop()
    _recv_event(c1, EVT_ESTOP_ACKED)
    time.sleep(0.7)
    # 超时前服务端加密发送 EVENT 0x0004，然后清密钥
    try:
        _recv_event(c1, EVT_SESSION_EXPIRED, timeout=0.8)
    except TimeoutError:
        pass
    time.sleep(0.4)
    stats = _wait_stats(server, "sessions_expired", 1)
    assert stats.get("sessions_expired", 0) >= 1
    # 旧会话帧不再被接受
    with pytest.raises(TimeoutError):
        c1.send_ping()
    # 新会话：锁存保留，需 release_estop + arm
    c2 = _client(server)
    c2.hello()
    c2.auth()
    c2.claim()
    c2.arm()
    _expect_error(c2, ERR_ESTOP)
    c2.release_estop()
    c2.arm()
    c2.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(c2, lambda t: t.x > 0.5).x > 0.5
    c1.close()
    c2.close()


# ---------- 控制 / TTL / 越界 ----------

@pytest.mark.cts_id("CTS-C-01")
def test_claim_without_arm_cannot_control(server):
    client = _client(server)
    client.hello()
    client.auth()
    client.claim()
    client.send_ctrl([16384, 0, 0, 0])
    assert abs(_wait_telem(client, lambda t: abs(t.x) < 1e-6).x) < 1e-6
    client.arm()
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    client.close()


@pytest.mark.cts_id("CTS-C-02")
def test_ttl_expired_frame_dropped(make_server):
    server = make_server(["--hold-next-ms", "250", "--ctrl-ttl-ms", "200", "--watchdog-ms", "600"])
    client = _client(server)
    client.connect()
    # 服务端的第一帧 CTRL 被 hold 250ms；TTL 200ms -> 丢弃，不得执行 2.0
    client.send_ctrl([32767, 0, 0, 0])
    for _ in range(20):
        client.send_ctrl([16384, 0, 0, 0])
        time.sleep(0.02)
    time.sleep(0.1)
    stats = _wait_stats(server, "ttl_dropped", 1)
    assert stats.get("ttl_dropped", 0) == 1
    assert stats.get("watchdog", 0) == 0
    seen = []
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        seen.append(_telem(client).x)
    assert seen and max(seen) < 1.2  # 未执行 2.0
    assert max(seen) > 0.5
    client.close()


@pytest.mark.cts_id("CTS-C-03")
def test_out_of_range_and_bad_mode_rejected(server):
    client = _client(server)
    client.connect()
    client.send_ctrl([32767, 0, 0, 0])  # scale=2.0 > range 1.5
    _expect_error(client, ERR_RANGE)
    assert _wait_stats(server, "invalid_ctrl", 1).get("invalid_ctrl", 0) >= 1
    assert abs(_wait_telem(client, lambda t: abs(t.x) < 1e-6).x) < 1e-6
    # 未知 mode：必须拒绝 + 计数，且不得运动
    client.arm()
    client.send_ctrl([16384, 0, 0, 0], mode=99)
    _expect_error(client, ERR_RANGE)
    stats = _wait_stats(server, "invalid_ctrl", 2)
    assert stats.get("invalid_ctrl", 0) >= 2
    assert abs(_wait_telem(client, lambda t: abs(t.x) < 1e-6).x) < 1e-6
    client.arm()
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    client.close()


# ---------- 安全 ----------

@pytest.mark.cts_id("CTS-S-03")
def test_watchdog_zero_and_requires_arm(server):
    client = _client(server)
    client.connect()
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    stop_start = time.monotonic()
    _recv_event(client, EVT_WATCHDOG, timeout=2.0)
    stats = _wait_stats(server, "watchdog", 1)
    assert stats.get("watchdog", 0) >= 1
    assert abs(_wait_telem(client, lambda t: abs(t.x) < 1e-6).x) < 1e-6
    assert time.monotonic() - stop_start <= 0.5  # ≤400 ms 停（加调度余量）
    client.send_ctrl([16384, 0, 0, 0])  # 未重新 arm，不得生效
    assert abs(_wait_telem(client, lambda t: abs(t.x) < 1e-6).x) < 1e-6
    client.arm()
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    client.close()


@pytest.mark.cts_id("CTS-S-04")
def test_estop_latch_and_two_step_reset(server):
    client = _client(server)
    client.connect()
    client.send_estop()
    _recv_event(client, EVT_ESTOP_ACKED)
    client.send_estop(0)  # ESTOP(0) 不清锁存
    client.send_ctrl([16384, 0, 0, 0])
    t = _telem(client)
    assert t.fault_flags & 0x02
    assert abs(t.x) < 1e-6
    client.release_estop()  # 只清锁存，不 arm
    client.send_ctrl([16384, 0, 0, 0])
    assert abs(_wait_telem(client, lambda t: abs(t.x) < 1e-6).x) < 1e-6
    client.arm()
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    client.close()


@pytest.mark.cts_id("CTS-S-05")
def test_replay_tamper_rejected(make_server):
    server = make_server(camera=True)
    client = _client(server)
    client.connect()
    # Agent→App 全局 seq：TELEM + VIDEO 跨流共 ≥20 帧且严格递增
    seen = 0
    end = time.monotonic() + 3.0
    while time.monotonic() < end and seen < 20:
        f = client.recv(timeout=end - time.monotonic())
        if f is not None and f.type in (frame.T_TELEM, frame.T_VIDEO):
            seen += 1
            if f.type == frame.T_VIDEO:
                break
    assert seen > 0
    assert client.agent_seq_ok
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    # 跨流重放：同一方向全局 seq，CTRL 与 FEEDBACK 复用 seq
    seq = (client.tx_seq + 1) & 0xFFFFFFFF
    ctrl = messages.pack_ctrl(0, [16384, 0, 0, 0], [0], 1)
    raw = frame.pack(frame.Frame(frame.T_CTRL, ctrl, session_id=client.session_id, seq=seq), client.ctx, to_robot=True)
    client.send_raw(raw)
    client.tx_seq = seq
    fb = messages.pack_feedback(0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    replay = frame.pack(frame.Frame(frame.T_FEEDBACK, fb, stream=frame.S_FEEDBACK,
                                    session_id=client.session_id, seq=seq), client.ctx, to_robot=True)
    client.send_raw(replay)
    time.sleep(0.1)
    assert _wait_stats(server, "replay_drop", 1).get("replay_drop", 0) >= 1
    # 篡改：密文翻转 + 重算 CRC -> AEAD 失败，不得生效
    seq2 = (seq + 1) & 0xFFFFFFFF
    raw = frame.pack(frame.Frame(frame.T_CTRL, messages.pack_ctrl(0, [32767, 0, 0, 0], [0], 1),
                                 session_id=client.session_id, seq=seq2), client.ctx, to_robot=True)
    client.send_raw(_tampered(raw))
    time.sleep(0.1)
    assert _wait_stats(server, "aead_fail", 1).get("aead_fail", 0) >= 1
    # CRC 错但密文未改：必须丢弃，不得执行
    seq3 = (seq2 + 1) & 0xFFFFFFFF
    raw = frame.pack(frame.Frame(frame.T_CTRL, messages.pack_ctrl(0, [32767, 0, 0, 0], [0], 1),
                                 session_id=client.session_id, seq=seq3), client.ctx, to_robot=True)
    bad_crc = bytearray(raw)
    bad_crc[40] ^= 0xFF  # 改载荷，不重算 CRC
    client.send_raw(bytes(bad_crc))
    time.sleep(0.1)
    assert _wait_stats(server, "aead_fail", 2).get("aead_fail", 0) >= 2
    client.tx_seq = seq3
    client.send_ctrl([16384, 0, 0, 0])
    assert _wait_telem(client, lambda t: t.x > 0.5).x > 0.5
    # Agent→App 全局 seq 单调
    assert client.agent_seq_ok
    client.close()


# ---------- 遥测 / 模型 / 视频 ----------

@pytest.mark.cts_id("CTS-T-01")
def test_telemetry_fields(server):
    client = _client(server)
    client.connect()
    t = _telem(client)
    assert 0 <= t.fsm_state <= 3
    assert t.remote_age_ms >= 0
    assert t.policy_name == "mock"
    client.close()


@pytest.mark.cts_id("CTS-M-01")
def test_model_state(server):
    client = _client(server)
    client.connect()
    f = client.recv_type(frame.T_MODEL_STATE, timeout=2.0)
    st = messages.unpack_model_state(f.payload)
    expected = capmod.joint_order_hash(client.caps["model"]["joint_order"])
    assert st["joint_order_hash"] == expected
    assert st["joint_count"] == len(client.caps["model"]["joint_order"])
    assert st["flags"] & 0x04
    client.close()


@pytest.mark.cts_id("CTS-V-01")
def test_video_rgb888(video_server):
    client = _client(video_server)
    client.connect()
    caps = client.caps
    stream = caps["streams"][0]
    assert stream["codecs"] == ["rgb888"] and stream["res"] == [160, 120]
    asm = VideoAssembler()
    got = None
    end = time.monotonic() + 3.0
    while time.monotonic() < end and got is None:
        f = client.recv(timeout=end - time.monotonic())
        if f and f.type == frame.T_VIDEO:
            got = asm.add(f.payload)
    assert got is not None
    meta, data = got
    assert len(data) == 160 * 120 * 3
    assert meta["frame_bytes"] == len(data)
    client.close()


def test_stale_state_injection(make_server):
    server = make_server(["--stale-state"])
    client = _client(server)
    client.connect()
    end = time.monotonic() + 0.8
    while time.monotonic() < end:
        f = client.recv(timeout=end - time.monotonic())
        assert not (f and f.type == frame.T_MODEL_STATE), "stale-state should not send MODEL_STATE"
    client.close()
