# Copyright (c) 2026-2027 zbc
"""检查仓库内 Markdown 相对链接是否有效。

内容：
    扫描所有 .md 文件中的相对链接（跳过 http/mailto/锚点与代码块），
    校验目标文件/目录存在。CI 与本地均可运行。

用法：
    python tools/check_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"\]\(([^)]+)\)")
FENCE_RE = re.compile(r"^```")


def strip_code_fences(text: str) -> str:
    out = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(line)
    return "\n".join(out)


def main() -> int:
    broken = []
    for path in ROOT.rglob("*.md"):
        if ".git" in path.parts:
            continue
        text = strip_code_fences(path.read_text(encoding="utf-8", errors="replace"))
        for match in LINK_RE.finditer(text):
            link = match.group(1).strip()
            if not link or link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target = link.split("#", 1)[0]
            if not target:
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)} -> {link}")
    for item in broken:
        print(f"[FAIL] {item}")
    if broken:
        print(f"{len(broken)} broken link(s)")
        return 1
    print("links ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
