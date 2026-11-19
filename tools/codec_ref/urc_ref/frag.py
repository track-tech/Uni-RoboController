# Copyright (c) 2026-2027 zbc
"""通用分片与重组（8 B 分片头）。

内容：
    分片头 msg_id u32 + pkt_idx u16 + pkt_cnt u16；payload 为分片块。
    重组器检测缺片、重复与超时（超时由调用方按时间戳清理）。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

FRAG_HDR = struct.Struct("<IHH")
MAX_MSG = 8 * 1024 * 1024


@dataclass
class Fragment:
    msg_id: int
    pkt_idx: int
    pkt_cnt: int
    data: bytes

    @property
    def is_last(self) -> bool:
        return self.pkt_idx == self.pkt_cnt - 1


def fragment(payload: bytes, mtu: int, msg_id: int) -> list[bytes]:
    """把 payload 切成若干“分片头 + 块”，每片总长 ≤ mtu。"""
    chunk = mtu - FRAG_HDR.size
    if chunk <= 0:
        raise ValueError("mtu too small")
    if len(payload) > MAX_MSG:
        raise ValueError("payload too large")
    count = max(1, (len(payload) + chunk - 1) // chunk)
    out = []
    for idx in range(count):
        part = payload[idx * chunk:(idx + 1) * chunk]
        out.append(FRAG_HDR.pack(msg_id, idx, count) + part)
    return out


def parse_fragment(data: bytes) -> Fragment:
    if len(data) < FRAG_HDR.size:
        raise ValueError("short fragment")
    msg_id, idx, cnt = FRAG_HDR.unpack_from(data, 0)
    if cnt == 0 or idx >= cnt:
        raise ValueError("bad fragment index")
    return Fragment(msg_id, idx, cnt, data[FRAG_HDR.size:])


class Reassembler:
    """按 msg_id 重组；重复分片丢弃，全齐即交付。"""

    def __init__(self, max_concurrent: int = 64, total_size: int = MAX_MSG):
        self.max_concurrent = max_concurrent
        self.total_size = total_size
        self._slots: dict[int, dict] = {}
        self.duplicates = 0
        self.dropped = 0

    def add(self, data: bytes) -> bytes | None:
        frag = parse_fragment(data)
        slot = self._slots.get(frag.msg_id)
        if slot is None:
            if len(self._slots) >= self.max_concurrent:
                self.dropped += 1
                return None
            slot = {"cnt": frag.pkt_cnt, "parts": [None] * frag.pkt_cnt, "size": 0}
            self._slots[frag.msg_id] = slot
        if slot["cnt"] != frag.pkt_cnt:
            self._slots.pop(frag.msg_id, None)
            self.dropped += 1
            return None
        if slot["parts"][frag.pkt_idx] is not None:
            self.duplicates += 1
            return None
        slot["parts"][frag.pkt_idx] = frag.data
        slot["size"] += len(frag.data)
        if slot["size"] > self.total_size:
            self._slots.pop(frag.msg_id, None)
            self.dropped += 1
            return None
        if all(p is not None for p in slot["parts"]):
            self._slots.pop(frag.msg_id, None)
            return b"".join(slot["parts"])
        return None

    def pending(self) -> int:
        return len(self._slots)
