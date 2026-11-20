# Copyright (c) 2026-2027 zbc
"""运行跨架构向量测试并生成 CTS-K-01 的 arch 报告。

用法：
    python tools/gen_arch_report.py --bin agent/build-arm64/urc_vectors \
        --vectors protocol/vectors --out artifacts/arch-report.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bin", required=True, help="urc_vectors 可执行文件")
    parser.add_argument("--vectors", default="protocol/vectors")
    parser.add_argument("--out", default="artifacts/arch-report.json")
    args = parser.parse_args()
    proc = subprocess.run([args.bin, args.vectors], capture_output=True, text=True)
    status = "passed" if proc.returncode == 0 else "failed"
    report = {
        "schema": "urc-cts-report/v1",
        "suite": "arch",
        "target": args.bin,
        "started_at": str(Path.cwd()),
        "cases": [{"id": "CTS-K-01", "status": status, "duration_ms": 0,
                   "detail": (proc.stdout or proc.stderr)[-500:]}],
        "summary": {"passed": 1 if status == "passed" else 0,
                     "failed": 0 if status == "passed" else 1, "skipped": 0, "xfail": 0},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print((proc.stdout or proc.stderr).strip())
    print(f"arch report: {status} -> {out}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
