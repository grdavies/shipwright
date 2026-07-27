"""PRD 081 R11 — concurrent doc-run exclusion fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_loop import doc_run_directory, doc_state_path, provision_doc_run
from wave_lock import doc_run_lock_path_for
from wave_target_lock import acquire_doc_run_lock


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def test_concurrent_doc_runs_same_topic_second_refused_before_artifacts(repo: Path) -> None:
    topic = "workflow-state-machine-hardening"
    first = acquire_doc_run_lock(repo, topic, "doc-first")
    assert first["verdict"] == "pass"

    second = acquire_doc_run_lock(repo, topic, "doc-second")
    assert second["verdict"] == "fail"
    assert second["error"] == "doc-run-lock-held"

    assert not doc_run_directory(repo, "doc-second").exists()
    assert not doc_state_path(repo, "doc-second").exists()

    lock_path = doc_run_lock_path_for(repo, topic)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    assert meta["runId"] == "doc-first"


def test_provision_refuses_when_lock_held_by_other_run(repo: Path) -> None:
    topic = "contention-topic"
    held = acquire_doc_run_lock(repo, topic, "doc-holder")
    assert held["verdict"] == "pass"

    blocked = provision_doc_run(repo, topic=topic, tier="Standard", run_id="doc-blocked")
    assert blocked["verdict"] == "fail"
    assert blocked["error"] == "doc-run-lock-held"
    assert not doc_run_directory(repo, "doc-blocked").exists()
