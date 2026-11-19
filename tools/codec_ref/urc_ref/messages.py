# Copyright (c) 2026-2027 zbc
"""URC 消息载荷编解码。

内容：
    HELLO/AUTH/CAPS/CTRL/TELEM/FEEDBACK/MODEL_STATE/ESTOP/EVENT/ERROR/
    SESSION_CTRL/PING/PONG/VIDEO/DISCOVER/ANNOUNCE 的打包与解析。
    TELEM 使用最小 protobuf wire 编码（字段见 protocol/proto/telemetry.proto）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable

from .crc import crc32c_final
from .frame import (
    T_ANNOUNCE, T_AUTH, T_AUTH_OK, T_CAPS, T_CTRL, T_DISCOVER, T_ERROR, T_EVENT,
    T_FEEDBACK, T_HELLO, T_HELLO_ACK, T_MODEL_STATE, T_SESSION_CTRL,
)

DISCOVERY_MAGIC = 0x31435255


# ---------- HELLO / HELLO_ACK ----------

def pack_hello(proto_major: int, proto_minor: int, role: int, flags: int,
               app_id: bytes, app_nonce: bytes, app_version: str) -> bytes:
    ver = app_version.encode("utf-8")
    if len(app_id) != 16 or len(app_nonce) != 16 or len(ver) > 255:
        raise ValueError("bad hello field")
    return struct.pack("<HHBH16s16sB", proto_major, proto_minor, role, flags,
                       app_id, app_nonce, len(ver)) + ver


def unpack_hello(payload: bytes) -> dict:
    (major, minor, role, flags, app_id, app_nonce, vlen) = struct.unpack_from("<HHBH16s16sB", payload, 0)
    off = struct.calcsize("<HHBH16s16sB")
    ver = payload[off:off + vlen].decode("utf-8")
    return {"proto_major": major, "proto_minor": minor, "role": role, "flags": flags,
            "app_id": app_id, "app_nonce": app_nonce, "app_version": ver}


@dataclass
class HelloAck:
    proto_major: int
    proto_minor: int
    session_id: int
    robot_id: str
    robot_name: str
    form: str
    robot_nonce: bytes
    caps_hash: int
    ctrl_port: int
    video_port: int
    depth_port: int
    map_port: int
    web_port: int
    auth_required: int


def pack_hello_ack(a: HelloAck) -> bytes:
    out = struct.pack("<HHI", a.proto_major, a.proto_minor, a.session_id)
    for s in (a.robot_id, a.robot_name, a.form):
        b = s.encode("utf-8")
        if len(b) > 255:
            raise ValueError("string too long")
        out += struct.pack("<B", len(b)) + b
    out += struct.pack("<16sI5H B", a.robot_nonce, a.caps_hash,
                       a.ctrl_port, a.video_port, a.depth_port, a.map_port,
                       a.web_port, a.auth_required)
    return out


def unpack_hello_ack(payload: bytes) -> HelloAck:
    major, minor, sid = struct.unpack_from("<HHI", payload, 0)
    off = 8
    strings = []
    for _ in range(3):
        n = payload[off]
        off += 1
        strings.append(payload[off:off + n].decode("utf-8"))
        off += n
    robot_nonce, caps_hash, ctrl, video, depth, map_port, web, auth = struct.unpack_from("<16sI5HB", payload, off)
    return HelloAck(major, minor, sid, strings[0], strings[1], strings[2],
                    robot_nonce, caps_hash, ctrl, video, depth, map_port, web, auth)


# ---------- AUTH / AUTH_OK ----------

def pack_auth(proof: bytes, client_id: bytes, client_name: str) -> bytes:
    name = client_name.encode("utf-8")
    if len(proof) != 32 or len(client_id) != 16 or len(name) > 255:
        raise ValueError("bad auth field")
    return proof + client_id + struct.pack("<B", len(name)) + name


def unpack_auth(payload: bytes) -> dict:
    proof = payload[:32]
    client_id = payload[32:48]
    n = payload[48]
    return {"proof": proof, "client_id": client_id, "client_name": payload[49:49 + n].decode("utf-8")}


def pack_auth_ok(role: int, key_confirm: bytes, server_ts_us: int) -> bytes:
    if len(key_confirm) != 8:
        raise ValueError("bad key_confirm")
    return struct.pack("<B8sQ", role, key_confirm, server_ts_us)


def unpack_auth_ok(payload: bytes) -> dict:
    role, confirm, ts = struct.unpack_from("<B8sQ", payload, 0)
    return {"role": role, "key_confirm": confirm, "server_ts_us": ts}


# ---------- CAPS ----------

CAPS_RAW = 0
CAPS_ZSTD = 1


def pack_caps(capability_json: bytes, encoding: int = CAPS_RAW) -> bytes:
    data = capability_json
    if encoding == CAPS_ZSTD:
        import zstandard
        data = zstandard.ZstdCompressor().compress(capability_json)
    crc = crc32c_final(capability_json)
    return struct.pack("<IIB", len(capability_json), crc, encoding) + data


def unpack_caps(payload: bytes) -> dict:
    raw_len, crc, encoding = struct.unpack_from("<IIB", payload, 0)
    data = payload[9:]
    if encoding == CAPS_ZSTD:
        import zstandard
        raw = zstandard.ZstdDecompressor().decompress(data, max_output_size=256 * 1024)
    else:
        raw = data
    if len(raw) != raw_len or crc32c_final(raw) != crc:
        raise ValueError("caps checksum mismatch")
    return {"raw": raw, "crc": crc, "encoding": encoding}


# ---------- CTRL ----------

def pack_ctrl(mode: int, axes: Iterable[int], buttons: Iterable[int], flags: int = 0) -> bytes:
    axes = list(axes)
    buttons = list(buttons)
    if len(axes) > 16 or len(buttons) not in (1, 2):
        raise ValueError("bad ctrl fields")
    out = struct.pack("<BBBB", mode, len(axes), len(buttons), flags)
    out += struct.pack("<" + "h" * len(axes), *axes)
    out += struct.pack("<" + "I" * len(buttons), *buttons)
    return out


def unpack_ctrl(payload: bytes) -> dict:
    mode, axis_count, button_words, flags = struct.unpack_from("<BBBB", payload, 0)
    off = 4
    axes = struct.unpack_from("<" + "h" * axis_count, payload, off)
    off += 2 * axis_count
    buttons = struct.unpack_from("<" + "I" * button_words, payload, off)
    return {"mode": mode, "axes": list(axes), "buttons": list(buttons), "flags": flags}


# ---------- ESTOP / EVENT / ERROR / SESSION_CTRL / PING ----------

def pack_estop(reason: int, ts_us: int) -> bytes:
    return struct.pack("<BQ", reason, ts_us)


def unpack_estop(payload: bytes) -> dict:
    reason, ts = struct.unpack_from("<BQ", payload, 0)
    return {"reason": reason, "ts_us": ts}


def pack_event(code: int, level: int, message: str) -> bytes:
    msg = message.encode("utf-8")[:255]
    return struct.pack("<HBB", code, level, len(msg)) + msg


def unpack_event(payload: bytes) -> dict:
    code, level, n = struct.unpack_from("<HBB", payload, 0)
    return {"code": code, "level": level, "message": payload[4:4 + n].decode("utf-8")}


def pack_error(code: int, message: str) -> bytes:
    msg = message.encode("utf-8")[:255]
    return struct.pack("<HB", code, len(msg)) + msg


def unpack_error(payload: bytes) -> dict:
    code, n = struct.unpack_from("<HB", payload, 0)
    return {"code": code, "message": payload[3:3 + n].decode("utf-8")}


def pack_session_ctrl(action: int) -> bytes:
    return struct.pack("<B3x", action)


def unpack_session_ctrl(payload: bytes) -> dict:
    return {"action": struct.unpack_from("<B", payload, 0)[0]}


# ---------- FEEDBACK ----------

def pack_feedback(video_ok: int, video_lost: int, packets_lost: int, recv_kbps: int,
                  decode_fps: int, decode_ms: int, rtt_us: int, jitter_us: int,
                  target_kbps: int, flags: int) -> bytes:
    return struct.pack("<IIIIHHII I H 2x", video_ok, video_lost, packets_lost, recv_kbps,
                       decode_fps, decode_ms, rtt_us, jitter_us, target_kbps, flags)


def unpack_feedback(payload: bytes) -> dict:
    v = struct.unpack_from("<IIIIHHIIIH", payload, 0)
    return dict(zip(("video_ok", "video_lost", "packets_lost", "recv_kbps",
                     "decode_fps", "decode_ms", "rtt_us", "jitter_us",
                     "target_kbps", "flags"), v))


# ---------- MODEL_STATE ----------

def pack_model_state(seq: int, ts_us: int, joint_order_hash: int, joint_count: int,
                     flags: int, frame_id: int, root_pos, root_quat,
                     joint_pos, joint_vel=None, joint_eff=None) -> bytes:
    out = struct.pack("<IQIHBB", seq, ts_us, joint_order_hash, joint_count, flags, frame_id)
    out += struct.pack("<3f", *root_pos) + struct.pack("<4f", *root_quat)
    out += struct.pack("<" + "f" * joint_count, *joint_pos)
    if joint_vel is not None:
        out += struct.pack("<" + "f" * joint_count, *joint_vel)
    if joint_eff is not None:
        out += struct.pack("<" + "f" * joint_count, *joint_eff)
    return out


def unpack_model_state(payload: bytes) -> dict:
    seq, ts_us, order_hash, count, flags, frame_id = struct.unpack_from("<IQIHBB", payload, 0)
    off = 20
    root_pos = struct.unpack_from("<3f", payload, off)
    off += 12
    root_quat = struct.unpack_from("<4f", payload, off)
    off += 16
    pos = struct.unpack_from("<" + "f" * count, payload, off)
    off += 4 * count
    vel = eff = None
    if flags & 0x01:
        vel = struct.unpack_from("<" + "f" * count, payload, off)
        off += 4 * count
    if flags & 0x02:
        eff = struct.unpack_from("<" + "f" * count, payload, off)
    return {"seq": seq, "ts_us": ts_us, "joint_order_hash": order_hash,
            "joint_count": count, "flags": flags, "frame_id": frame_id,
            "root_pos": list(root_pos), "root_quat": list(root_quat),
            "joint_pos": list(pos), "joint_vel": list(vel) if vel else None,
            "joint_eff": list(eff) if eff else None}


# ---------- VIDEO ----------

VIDEO_HEADER = struct.Struct("<IQIHHHB")


def pack_video(frame_id: int, frame_ts_us: int, frame_bytes: int, pkt_idx: int,
               pkt_cnt: int, group_id: int, media_flags: int, data: bytes) -> bytes:
    return VIDEO_HEADER.pack(frame_id, frame_ts_us, frame_bytes, pkt_idx,
                             pkt_cnt, group_id, media_flags) + data


def unpack_video(payload: bytes) -> dict:
    fid, ts, fbytes, idx, cnt, gid, mflags = VIDEO_HEADER.unpack_from(payload, 0)
    return {"frame_id": fid, "frame_ts_us": ts, "frame_bytes": fbytes,
            "pkt_idx": idx, "pkt_cnt": cnt, "group_id": gid,
            "media_flags": mflags, "data": payload[VIDEO_HEADER.size:]}


# ---------- TELEM（最小 protobuf wire） ----------

def _varint(v: int) -> bytes:
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def _tag(field: int, wire: int) -> bytes:
    return _varint((field << 3) | wire)


def _float_field(field: int, value: float) -> bytes:
    return _tag(field, 5) + struct.pack("<f", value)


def _packed_floats(field: int, values) -> bytes:
    values = list(values)
    if not values:
        return b""
    data = struct.pack("<" + "f" * len(values), *values)
    return _tag(field, 2) + _varint(len(data)) + data


@dataclass
class Telemetry:
    seq: int = 0
    ts_us: int = 0
    fsm_state: int = 0
    fault_flags: int = 0
    battery_pct: int = 0
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    joint_q: tuple = ()
    joint_dq: tuple = ()
    joint_tau: tuple = ()
    imu_quat: tuple = ()
    imu_gyro: tuple = ()
    policy_name: str = ""
    inference_us: int = 0
    episode_len: int = 0
    queue_depth: int = 0
    link_rtt_us: int = 0
    link_loss_pct: int = 0
    remote_age_ms: int = 0
    map_revision: int = 0


def pack_telem(t: Telemetry) -> bytes:
    out = b""
    for field, value in ((1, t.seq), (2, t.ts_us), (3, t.fsm_state), (4, t.fault_flags),
                         (5, t.battery_pct)):
        out += _tag(field, 0) + _varint(int(value) & ((1 << 64) - 1))
    out += _float_field(6, t.x) + _float_field(7, t.y) + _float_field(8, t.yaw)
    out += _packed_floats(9, t.joint_q) + _packed_floats(10, t.joint_dq) + _packed_floats(11, t.joint_tau)
    out += _packed_floats(12, t.imu_quat) + _packed_floats(13, t.imu_gyro)
    if t.policy_name:
        b = t.policy_name.encode("utf-8")
        out += _tag(14, 2) + _varint(len(b)) + b
    for field, value in ((15, t.inference_us), (16, t.episode_len), (17, t.queue_depth),
                         (18, t.link_rtt_us), (19, t.link_loss_pct), (20, t.remote_age_ms),
                         (21, t.map_revision)):
        out += _tag(field, 0) + _varint(int(value) & ((1 << 64) - 1))
    return out


def _read_varint(buf: bytes, off: int):
    shift = 0
    value = 0
    while True:
        b = buf[off]
        off += 1
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value, off
        shift += 7


def unpack_telem(payload: bytes) -> Telemetry:
    t = Telemetry()
    off = 0
    floats: dict[int, list] = {}
    while off < len(payload):
        key, off = _read_varint(payload, off)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, off = _read_varint(payload, off)
            setattr(t, {1: "seq", 2: "ts_us", 3: "fsm_state", 4: "fault_flags",
                        5: "battery_pct", 15: "inference_us", 16: "episode_len",
                        17: "queue_depth", 18: "link_rtt_us", 19: "link_loss_pct",
                        20: "remote_age_ms", 21: "map_revision"}[field], value)
        elif wire == 5:
            value = struct.unpack_from("<f", payload, off)[0]
            off += 4
            setattr(t, {6: "x", 7: "y", 8: "yaw"}[field], value)
        elif wire == 2:
            length, off = _read_varint(payload, off)
            data = payload[off:off + length]
            off += length
            if field == 14:
                t.policy_name = data.decode("utf-8")
            elif field in (9, 10, 11, 12, 13):
                floats.setdefault(field, []).extend(struct.unpack("<" + "f" * (len(data) // 4), data))
        else:
            raise ValueError(f"unsupported wire type {wire}")
    for field, name in ((9, "joint_q"), (10, "joint_dq"), (11, "joint_tau"),
                        (12, "imu_quat"), (13, "imu_gyro")):
        if field in floats:
            setattr(t, name, tuple(floats[field]))
    return t


# ---------- DISCOVER / ANNOUNCE（独立格式，无 32B 帧头） ----------

def pack_discover(app_nonce: bytes, app_id: bytes, flags: int = 0) -> bytes:
    body = struct.pack("<IBBBB16s16s", DISCOVERY_MAGIC, 1, T_DISCOVER, flags, 0, app_nonce, app_id)
    return body + struct.pack("<I", crc32c_final(body))


@dataclass
class Announce:
    robot_id: str
    robot_name: str
    form: str
    ctrl_port: int
    video_port: int
    depth_port: int
    map_port: int
    web_port: int
    caps_hash: int
    pair_state: int
    proto_major: int = 1
    proto_minor: int = 0


def pack_announce(a: Announce, flags: int = 0) -> bytes:
    body = struct.pack("<IBBBBB", DISCOVERY_MAGIC, 1, T_ANNOUNCE, flags, 0, 0)
    for s in (a.robot_id, a.robot_name, a.form):
        b = s.encode("utf-8")
        body += struct.pack("<B", len(b)) + b
    body += struct.pack("<5HIBHH", a.ctrl_port, a.video_port, a.depth_port,
                        a.map_port, a.web_port, a.caps_hash, a.pair_state,
                        a.proto_major, a.proto_minor)
    return body + struct.pack("<I", crc32c_final(body))


def unpack_announce(data: bytes) -> Announce:
    magic, ver, mtype, _flags, _r, _r2 = struct.unpack_from("<IBBBBB", data, 0)
    if magic != DISCOVERY_MAGIC or ver != 1 or mtype != T_ANNOUNCE:
        raise ValueError("bad announce")
    if crc32c_final(data[:-4]) != struct.unpack_from("<I", data, len(data) - 4)[0]:
        raise ValueError("bad announce crc")
    off = 10
    strings = []
    for _ in range(3):
        n = data[off]
        off += 1
        strings.append(data[off:off + n].decode("utf-8"))
        off += n
    ctrl, video, depth, map_port, web, caps_hash, pair_state, major, minor = struct.unpack_from("<5HIBHH", data, off)
    return Announce(strings[0], strings[1], strings[2], ctrl, video, depth,
                    map_port, web, caps_hash, pair_state, major, minor)
