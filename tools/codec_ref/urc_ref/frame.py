# Copyright (c) 2026-2027 zbc
"""协议帧编解码（32 B 帧头）。

内容：
    URC1 帧头打包/解包、CRC32C、可选 AES-256-GCM 加解密。
    加密帧：payload_len 为明文长度；线上载荷 = 密文 + 16 B tag；
    CRC 覆盖“帧头(crc 置 0) + 线上载荷”；GCM AAD = 帧头且 crc 字段置 0。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

from .crc import crc32c_final

MAGIC = 0x31435255  # ASCII "URC1" 小端
VERSION = 1
HEADER_SIZE = 32
MAX_PAYLOAD = 1200

# 消息类型
T_HELLO = 0x01
T_HELLO_ACK = 0x02
T_AUTH = 0x03
T_AUTH_OK = 0x04
T_CAPS = 0x05
T_CTRL = 0x06
T_TELEM = 0x07
T_FEEDBACK = 0x08
T_PING = 0x09
T_PONG = 0x0A
T_ESTOP = 0x0B
T_CONFIG = 0x0C
T_CONFIG_ACK = 0x0D
T_EVENT = 0x0E
T_ERROR = 0x0F
T_VIDEO = 0x10
T_VIDEO_FEC = 0x11
T_DEPTH = 0x12
T_MAP_META = 0x13
T_MAP_REQ = 0x14
T_MAP_TILE = 0x15
T_MAP_ACK = 0x16
T_SESSION_CTRL = 0x17
T_TIME_SYNC = 0x18
T_MODEL_STATE = 0x19
T_DISCOVER = 0x20
T_ANNOUNCE = 0x21

# flags
F_ENCRYPTED = 0x01
F_KEYFRAME = 0x02
F_FEC = 0x04
F_LAST_FRAG = 0x08
F_ACK_REQ = 0x10
F_RESEND = 0x20

# 流
S_CTRL = 0
S_TELEMETRY = 1
S_VIDEO = 2
S_DEPTH = 3
S_MAP = 4
S_CONFIG = 5
S_FEEDBACK = 6

HEADER = struct.Struct("<IBBBBIIQHHI")


@dataclass
class Frame:
    type: int
    payload: bytes = b""
    flags: int = 0
    stream: int = S_CTRL
    session_id: int = 0
    seq: int = 0
    ts_us: int = 0
    plain_payload_len: int = 0
    # 解码后填充
    raw: bytes = b""
    crc: int = 0

    @property
    def encrypted(self) -> bool:
        return bool(self.flags & F_ENCRYPTED)


def _header_bytes(magic: int, version: int, ftype: int, flags: int, stream: int,
                  session_id: int, seq: int, ts_us: int, payload_len: int, crc: int) -> bytes:
    return HEADER.pack(magic, version, ftype, flags, stream, session_id, seq,
                       ts_us, payload_len & 0xFFFF, 0, crc & 0xFFFFFFFF)


def _seal(f: Frame, aead, to_robot: bool) -> bytes:
    """加密并打包一帧。to_robot=True 表示 App→Agent 方向。"""
    header = _header_bytes(MAGIC, VERSION, f.type, f.flags | F_ENCRYPTED, f.stream,
                           f.session_id, f.seq, f.ts_us, len(f.payload), 0)
    nonce = aead.make_nonce(f.seq, to_robot=to_robot)
    key = aead.app2robot_key if to_robot else aead.robot2app_key
    cipher = aead.encrypt(key, nonce, header, f.payload)
    crc = crc32c_final(header + cipher)
    header = _header_bytes(MAGIC, VERSION, f.type, f.flags | F_ENCRYPTED, f.stream,
                           f.session_id, f.seq, f.ts_us, len(f.payload), crc)
    return header + cipher


def pack(f: Frame, aead=None, to_robot: bool = True) -> bytes:
    """打包一帧；aead 不为 None 时加密（to_robot 决定方向与密钥）。"""
    if len(f.payload) > MAX_PAYLOAD:
        raise ValueError("payload too large")
    if aead is not None:
        return _seal(f, aead, to_robot)
    header = _header_bytes(MAGIC, VERSION, f.type, f.flags, f.stream, f.session_id,
                           f.seq, f.ts_us, len(f.payload), 0)
    crc = crc32c_final(header + f.payload)
    header = _header_bytes(MAGIC, VERSION, f.type, f.flags, f.stream, f.session_id,
                           f.seq, f.ts_us, len(f.payload), crc)
    return header + f.payload


def unpack(data: bytes, aead=None, from_robot: bool = False) -> Frame:
    """解包并校验；加密帧需提供 aead（from_robot=True 表示这是 Agent→App 的帧）。"""
    if len(data) < HEADER_SIZE:
        raise ValueError("short frame")
    (magic, version, ftype, flags, stream, session_id, seq, ts_us,
     payload_len, _reserved, crc) = HEADER.unpack_from(data, 0)
    if magic != MAGIC:
        raise ValueError("bad magic")
    if version != VERSION:
        raise ValueError("bad version")
    encrypted = bool(flags & F_ENCRYPTED)
    body = data[HEADER_SIZE:]
    if encrypted:
        if len(body) != payload_len + 16:
            raise ValueError("bad encrypted length")
    elif len(body) != payload_len:
        raise ValueError("bad length")
    header0 = _header_bytes(magic, version, ftype, flags, stream, session_id,
                            seq, ts_us, payload_len, 0)
    if crc32c_final(header0 + body) != crc:
        raise ValueError("bad crc")
    if encrypted:
        if aead is None:
            raise ValueError("encrypted frame requires aead")
        nonce = aead.make_nonce(seq, to_robot=not from_robot)
        key = aead.robot2app_key if from_robot else aead.app2robot_key
        payload = aead.decrypt(key, nonce, header0, body)
    else:
        payload = body
    return Frame(type=ftype, payload=payload, flags=flags, stream=stream,
                 session_id=session_id, seq=seq, ts_us=ts_us,
                 plain_payload_len=payload_len, raw=data, crc=crc)


# ---------- 便捷构造 ----------

def ctrl_frame(session_id: int, seq: int, ts_us: int, payload: bytes, flags: int = 0) -> Frame:
    return Frame(T_CTRL, payload, flags=flags, stream=S_CTRL,
                 session_id=session_id, seq=seq, ts_us=ts_us)


def estop_frame(session_id: int, seq: int, ts_us: int, reason: int, flags: int = F_ACK_REQ) -> Frame:
    return Frame(T_ESTOP, struct.pack("<BQ", reason, ts_us), flags=flags,
                 stream=S_CTRL, session_id=session_id, seq=seq, ts_us=ts_us)


def ping_frame(session_id: int, seq: int, ts_us: int) -> Frame:
    return Frame(T_PING, struct.pack("<Q", ts_us), stream=S_CTRL,
                 session_id=session_id, seq=seq, ts_us=ts_us)


def pong_frame(session_id: int, seq: int, ts_us: int, echo_ts_us: int) -> Frame:
    return Frame(T_PONG, struct.pack("<Q", echo_ts_us), stream=S_CTRL,
                 session_id=session_id, seq=seq, ts_us=ts_us)
