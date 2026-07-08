"""Pytest wrapper — PRD 057 R29 visibility-tier alias-precedence fixture.

Runs the standalone fixture harness at
``scripts/test/fixtures/planning-visibility-aliases/harness.py`` so the deterministic
old->new alias-precedence table (new key wins; mixed config never weakens the
redaction default; deprecated-only matches pre-rename behavior; deprecation warning
shape) is exercised in the required pytest planning shard without duplicating
fixture logic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_FIXTURE_REL = "scripts/test/fixtures/planning-visibility-aliases/harness.py"


def _load(repo_root: Path):
    path = repo_root / _FIXTURE_REL
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_visibility_aliases_harness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_visibility_aliases_behavior(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo_root)
    assert _load(repo_root).main() == 0
