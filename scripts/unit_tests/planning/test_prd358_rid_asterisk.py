"""PRD 358 phase 9 — asterisk and hyphen RID bullet extraction (R7)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_FIXTURE_REL = "scripts/test/fixtures/rid-asterisk-linear-roundtrip/harness.py"


def _load(repo_root: Path):
    path = repo_root / _FIXTURE_REL
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_rid_asterisk_harness", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_rid_asterisk_linear_roundtrip_fixture(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo_root)
    mod = _load(repo_root)
    assert mod.FIXTURE_ID == "rid-asterisk-linear-roundtrip"
    assert mod.main() == 0
