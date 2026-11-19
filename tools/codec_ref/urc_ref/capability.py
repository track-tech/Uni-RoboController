# Copyright (c) 2026-2027 zbc
"""能力描述（capability）工具。

内容：
    规范化 JSON、caps_hash、joint_order_hash、加载与 Schema 校验。
"""

from __future__ import annotations

import json
import hashlib

from .crc import crc32c_final


def canonical_json(obj) -> bytes:
    """规范化 JSON：排序键、紧凑分隔符、UTF-8；用于 caps_hash 与签名。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def caps_hash(obj) -> int:
    """caps_hash = SHA-256(canonical_json)[0:4]，按小端 u32。"""
    return int.from_bytes(hashlib.sha256(canonical_json(obj)).digest()[:4], "little")


def joint_order_hash(joint_order: list[str]) -> int:
    """joint_order_hash = CRC32C(UTF-8(names 以 \\n 连接))。"""
    data = "\n".join(joint_order).encode("utf-8")
    return crc32c_final(data)


def load_capability(path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate_capability(obj, schema: dict) -> None:
    import jsonschema
    jsonschema.validate(instance=obj, schema=schema)
