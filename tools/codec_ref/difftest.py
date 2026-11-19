# Copyright (c) 2026-2027 zbc
"""跨实现差分测试。

内容：
    校验测试向量与 Python 参考实现同步，并调用 C++ 向量测试（若已构建）；
    可选调用 Kotlin 测试（android 目录存在时）。用于 CI 与本地验收。

用法：
    python tools/codec_ref/difftest.py --all
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run(cmd: list[str]) -> int:
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def find_agent_test() -> Path | None:
    for name in ("urc_vectors.exe", "urc_vectors"):
        path = ROOT / "agent" / "build" / name
        if path.exists():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    failed = 0
    failed |= run([sys.executable, str(ROOT / "tools/codec_ref/gen_vectors.py"), "--check"])
    vectors = ROOT / "protocol" / "vectors"
    binary = find_agent_test()
    if binary:
        failed |= run([str(binary), str(vectors)])
    else:
        print("skip: C++ vector binary not built (agent/build/urc_vectors)")
    if args.all and (ROOT / "android" / "settings.gradle.kts").exists():
        gradlew = ROOT / "android" / "gradlew"
        if gradlew.exists():
            failed |= run([str(gradlew), ":core:protocol:test"])
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
