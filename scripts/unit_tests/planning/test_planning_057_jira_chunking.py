"""Pytest wrapper — PRD 057 R9 provider-aware Jira chunking fixture.

Runs the standalone fixture harness at
``scripts/test/fixtures/planning-jira-chunking/harness.py`` so the
Jira-payload-size pre-chunking behavior in the standard write path is
exercised in the required pytest planning shard without duplicating fixture
logic.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_FIXTURE_REL = "scripts/test/fixtures/planning-jira-chunking/harness.py"


def _load(repo_root: Path):
    path = repo_root / _FIXTURE_REL
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_jira_chunking_harness", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_jira_chunking_standard_write_path_behavior(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(repo_root)
    assert _load(repo_root).main() == 0
