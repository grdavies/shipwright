"""Pytest wrapper — PRD 057 R21 / 21b memory backend provider round-trip fixture.

Runs the standalone fixture harness at
``scripts/test/fixtures/memory-roundtrip/harness.py`` so the provider
round-trip + R21a local-cache-fallback behavior is exercised in the required
pytest planning shard without duplicating fixture logic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_FIXTURE_REL = "scripts/test/fixtures/memory-roundtrip/harness.py"


def _load(repo_root: Path):
    path = repo_root / _FIXTURE_REL
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_memory_roundtrip_harness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_memory_backend_provider_round_trip_and_local_cache_fallback(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(repo_root)
    assert _load(repo_root).main() == 0
