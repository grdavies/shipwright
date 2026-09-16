"""Pytest wrapper — PRD 357 Linear-aware chunking fixture."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_FIXTURE_REL = "scripts/test/fixtures/planning-linear-chunk/harness.py"


def _load(repo_root: Path):
    path = repo_root / _FIXTURE_REL
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_linear_chunk_harness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_linear_chunking_fixture(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo_root)
    assert _load(repo_root).main() == 0
