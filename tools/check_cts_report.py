# Copyright (c) 2026-2027 zbc
"""校验 CTS 报告：P0 ID 集合、全部 passed、skipped/xfail=0。

用法：
    python tools/check_cts_report.py --dynamic conformance/cts-report.json --arch artifacts/arch-report.json
    python tools/check_cts_report.py --suite dynamic --dynamic conformance/cts-report.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

P0_DYNAMIC = ["CTS-D-01", "CTS-P-01", "CTS-P-02", "CTS-S-01", "CTS-S-02", "CTS-C-01",
              "CTS-C-02", "CTS-C-03", "CTS-S-03", "CTS-S-04", "CTS-S-05"]
P0_ARCH = ["CTS-K-01"]


def load(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"report not found: {path}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise SystemExit(f"bad report {path}: {exc}") from exc
    if data.get("schema") != "urc-cts-report/v1":
        raise SystemExit(f"bad schema in {path}: {data.get('schema')}")
    return data


def check(data: dict, expected: list[str], name: str) -> list[str]:
    errors = []
    cases = data.get("cases") or []
    ids = [c.get("id") for c in cases]
    missing = sorted(set(expected) - set(ids))
    if missing:
        errors.append(f"{name}: missing P0 IDs {missing}")
    for case in cases:
        if case.get("id") not in expected:
            continue
        status = case.get("status")
        if status != "passed":
            errors.append(f"{name}: {case.get('id')} status={status}")
    summary = data.get("summary") or {}
    for key in ("skipped", "xfail"):
        if summary.get(key, 0) != 0:
            errors.append(f"{name}: summary.{key}={summary.get(key)}")
    if summary.get("failed", 0) != 0:
        errors.append(f"{name}: summary.failed={summary.get('failed')}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["dynamic", "arch", "all"], default="all")
    parser.add_argument("--dynamic", default="conformance/cts-report.json")
    parser.add_argument("--arch", default="artifacts/arch-report.json")
    args = parser.parse_args()
    errors: list[str] = []
    if args.suite in ("dynamic", "all"):
        errors += check(load(args.dynamic), P0_DYNAMIC, "dynamic")
    if args.suite in ("arch", "all"):
        errors += check(load(args.arch), P0_ARCH, "arch")
    if errors:
        print("CTS REPORT CHECK FAILED")
        for err in errors:
            print(f"  - {err}")
        return 1
    print("CTS report OK: P0 all passed, skipped=0, xfail=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
