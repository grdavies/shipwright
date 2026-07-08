"""Pytest wrapper — PRD 057 R8 chunk-manifest id rewrite + reassembly fixture.

Runs the standalone fixture harness at
``scripts/test/fixtures/planning-chunk-reassembly/harness.py`` so the
real-id manifest rewrite (and no-stale-comment reassembly) behavior is
exercised in the required pytest planning shard without duplicating fixture
logic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_FIXTURE_REL = "scripts/test/fixtures/planning-chunk-reassembly/harness.py"


def _load(repo_root: Path):
    path = repo_root / _FIXTURE_REL
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_chunk_reassembly_harness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chunk_reassembly_real_id_rewrite_behavior(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo_root)
    assert _load(repo_root).main() == 0
