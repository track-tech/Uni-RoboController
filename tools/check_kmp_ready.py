# Copyright (c) 2026-2027 zbc
"""检查共享协议层的 KMP-ready 边界。

内容：
    Android 的 core:protocol 不得引用 android.* / androidx.*，便于后续迁移 iOS/桌面/Web。
    目录尚不存在时视为通过（M0 前）。

用法：
    python tools/check_kmp_ready.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "android" / "core" / "protocol"
BAD_RE = re.compile(r"^\s*import\s+(android|androidx)\.")


def main() -> int:
    if not TARGET.exists():
        print("skip: android/core/protocol not present")
        return 0
    bad = []
    for path in TARGET.rglob("*.kt"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BAD_RE.match(line):
                bad.append(f"{path.relative_to(ROOT)}:{lineno}: {line.strip()}")
    for item in bad:
        print(f"[FAIL] {item}")
    if bad:
        return 1
    print("kmp-ready ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
