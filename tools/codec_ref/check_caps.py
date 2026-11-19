# Copyright (c) 2026-2027 zbc
"""校验 capability JSON。

内容：
    用 JSON Schema 校验 protocol/examples 下所有 capability，
    并校验 model.joint_order_hash 与 joint_order 是否一致。

用法：
    python tools/codec_ref/check_caps.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from urc_ref.capability import joint_order_hash, validate_capability  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--examples", default=str(ROOT / "protocol" / "examples"))
    parser.add_argument("--schema", default=str(ROOT / "protocol" / "schemas" / "capability.schema.json"))
    args = parser.parse_args()

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    failed = 0
    for path in sorted(Path(args.examples).glob("capability.*.json")):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            validate_capability(obj, schema)
        except Exception as exc:  # noqa: BLE001
            print(f"[FAIL] {path.name}: schema: {exc}")
            failed += 1
            continue
        model = obj.get("model") or {}
        order = model.get("joint_order") or []
        if order:
            want = joint_order_hash(order)
            got = model.get("joint_order_hash")
            if got != want:
                print(f"[FAIL] {path.name}: joint_order_hash {got} != {want}")
                failed += 1
                continue
        print(f"[OK]   {path.name}")
    if failed:
        print(f"{failed} capability file(s) failed")
        return 1
    print("all capabilities ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
