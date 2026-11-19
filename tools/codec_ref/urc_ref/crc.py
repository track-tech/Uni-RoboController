# Copyright (c) 2026-2027 zbc
"""CRC-32/ISCSI（Castagnoli）实现。

内容：
    反射多项式 0x82F63B78，init 0xFFFFFFFF，xorout 0xFFFFFFFF。
    校验串 b"123456789" 的结果为 0xE3069283。
"""

_POLY = 0x82F63B78


def _make_table():
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            crc = (crc >> 1) ^ _POLY if crc & 1 else crc >> 1
        table.append(crc & 0xFFFFFFFF)
    return table


_TABLE = _make_table()


def crc32c(data: bytes, crc: int = 0xFFFFFFFF) -> int:
    """计算 CRC-32C；支持分段累计（先传 crc 初值 0xFFFFFFFF，勿传 0）。"""
    for byte in data:
        crc = _TABLE[(crc ^ byte) & 0xFF] ^ (crc >> 8)
    return crc & 0xFFFFFFFF


def crc32c_final(data: bytes) -> int:
    """一次性计算 CRC-32C（含最终异或）。"""
    return crc32c(data) ^ 0xFFFFFFFF


if __name__ == "__main__":
    assert crc32c_final(b"123456789") == 0xE3069283
    print("crc32c ok")
