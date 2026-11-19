# Copyright (c) 2026-2027 zbc
"""重新计算 capability 示例中的 joint_order_hash。

内容：
    修改 joint_order 后运行本脚本，保持 model.joint_order_hash 与顺序一致。

用法：
    python tools/codec_ref/update_example_hashes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from urc_ref.capability import joint_order_hash  # noqa: E402


def main() -> int:
    for path in sorted((ROOT / "protocol" / "examples").glob("capability*.json")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        model = obj.get("model") or {}
        order = model.get("joint_order") or []
        if not order:
            continue
        model["joint_order_hash"] = joint_order_hash(order)
        obj["model"] = model
        path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{path.name}: joint_order_hash={model['joint_order_hash']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
