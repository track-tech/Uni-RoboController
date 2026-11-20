# Copyright (c) 2026-2027 zbc
"""CTS 静态组：capability Schema、测试向量同步与 JSON 合法性。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.static
def test_capabilities_schema():
    proc = subprocess.run([sys.executable, str(ROOT / "tools/codec_ref/check_caps.py")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.static
def test_vectors_up_to_date():
    proc = subprocess.run([sys.executable, str(ROOT / "tools/codec_ref/gen_vectors.py"), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.static
@pytest.mark.parametrize("name", ["frames", "crypto", "frag", "session", "replay"])
def test_vectors_parse(name):
    path = ROOT / "protocol" / "vectors" / f"{name}.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["cases"], "empty vector file"
    for case in doc["cases"]:
        assert "name" in case and "expect" in case
        if name == "replay":
            assert case.get("frames"), "empty replay case"
        else:
            assert "given" in case


@pytest.mark.static
def test_capability_examples_parse():
    for path in (ROOT / "protocol" / "examples").glob("capability*.json"):
        obj = json.loads(path.read_text(encoding="utf-8"))
        assert obj["schema"] == "urc-capability/v1"
