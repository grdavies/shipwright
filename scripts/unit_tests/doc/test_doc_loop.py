"""PRD 085 R9/R10 — doc-loop terminal completion and doc-driver env scoping."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from check_frozen_lib import is_driver_invoked
from doc_loop import (
    acknowledge_checkpoint,
    consume_agent_stage,
    execute_mechanical_stage,
    freeze_stage_artifact,
    load_doc_state,
    provision_doc_run,
    run_related_work_scan,
    set_pending_checkpoint,
)
from wave_lock import doc_run_lock_path_for


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        with patch("wave_state.path_normalize_anchor", return_value=repo.resolve()):
            yield


def _verified_freeze(stage: str) -> dict:
    key = "prd" if stage == "freeze-prd" else "tasks"
    return {
        "verdict": "pass",
        "artifactKey": key,
        "receipt": {
            "owner": "doc-loop:test",
            "durabilityState": "verified",
            "lifecycleState": "frozen",
            "revision": "rev",
        },
    }


def _feature_seed_pass() -> dict:
    return {
        "verdict": "pass",
        "action": "feature-seed",
        "receipt": {
            "transitionName": "feature-seed",
            "publicationMode": "file-store-feature-seed",
            "remoteState": {"dryRun": True},
        },
    }


def _drive_doc_run_to_complete(repo: Path, topic: str) -> str:
    provisioned = provision_doc_run(repo, topic=topic, tier="Standard")
    assert provisioned["verdict"] == "pass"
    run_id = str(provisioned["runId"])
    lock_path = doc_run_lock_path_for(repo, topic)
    assert lock_path.is_file(), "doc-run lock should exist after provision"

    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "triage", outcome={"unitIds": {"prd": "prd-085", "tasks": "tasks-085"}})
    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "prd", outcome={})
    state = load_doc_state(repo, run_id)
    consume_agent_stage(repo, state, "doc-review", outcome={})
    state = load_doc_state(repo, run_id)

    with patch("doc_loop.run_related_work_scan", return_value={"verdict": "ok", "proposals": []}):
        execute_mechanical_stage(repo, state, "related-work")
    state = load_doc_state(repo, run_id)

    with patch("doc_loop.freeze_stage_artifact", side_effect=lambda _r, _s, stage: _verified_freeze(stage)):
        execute_mechanical_stage(repo, state, "freeze-prd")
    state = load_doc_state(repo, run_id)

    consume_agent_stage(repo, state, "tasks", outcome={})
    state = load_doc_state(repo, run_id)

    with patch("doc_loop.freeze_stage_artifact", side_effect=lambda _r, _s, stage: _verified_freeze(stage)):
        execute_mechanical_stage(repo, state, "freeze-tasks")
    state = load_doc_state(repo, run_id)

    set_pending_checkpoint(repo, state)
    state = load_doc_state(repo, run_id)
    acknowledge_checkpoint(repo, state)
    state = load_doc_state(repo, run_id)

    with patch("doc_loop.run_feature_seed", return_value=_feature_seed_pass()):
        result = execute_mechanical_stage(repo, state, "feature-seed")

    final = load_doc_state(repo, run_id)
    assert final["stage"] == "complete"
    assert final["verdict"] == "complete"
    assert result.get("lockRelease", {}).get("verdict") == "pass"
    return run_id


def test_terminal_completion_releases_doc_run_lock(repo: Path) -> None:
    topic = "terminal-release-topic"
    run_id = _drive_doc_run_to_complete(repo, topic)
    lock_path = doc_run_lock_path_for(repo, topic)
    assert not lock_path.is_file(), "doc-run lock must be released after terminal complete"

    state = load_doc_state(repo, run_id)
    assert state["verdict"] == "complete"


def _state_with_prd(repo: Path, run_id: str) -> dict:
    state = load_doc_state(repo, run_id)
    state["unitIds"] = {"prd": "085-prd-demo", "tasks": "tasks-085-demo"}
    state["artifactPaths"] = {
        "prd": "docs/prds/085-prd-demo/prd.md",
        "tasks": "docs/prds/085-prd-demo/tasks-085-demo.md",
    }
    return state


def test_doc_driver_env_restored_after_related_work_scan(repo: Path) -> None:
    """R10 — driver-invoked signal via parameter; SW_DOC_DRIVER not leaked."""
    prd_dir = repo / "docs/prds/085-prd-demo"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (prd_dir / "prd.md").write_text("---\ntype: prd\n---\n# Demo\n", encoding="utf-8")

    provisioned = provision_doc_run(repo, topic="driver-env-scope", tier="Standard")
    run_id = str(provisioned["runId"])
    state = _state_with_prd(repo, run_id)

    os.environ.pop("SW_DOC_DRIVER", None)
    captured: list[tuple[bool | None, str | None]] = []

    def capture_scan(_root, _source, *, mode, driver_invoked=None, **kwargs):
        captured.append((driver_invoked, os.environ.get("SW_DOC_DRIVER")))
        return {"verdict": "ok", "proposals": []}

    with patch("planning_related.source_from_path", return_value=object()):
        with patch("planning_related.scan_related", side_effect=capture_scan):
            run_related_work_scan(repo, state)

    assert captured == [(True, None)]
    assert os.environ.get("SW_DOC_DRIVER") is None

    os.environ["SW_DOC_DRIVER"] = "legacy"
    with patch("planning_related.source_from_path", return_value=object()):
        with patch("planning_related.scan_related", side_effect=capture_scan):
            run_related_work_scan(repo, state)
    assert os.environ.get("SW_DOC_DRIVER") == "legacy"


def test_freeze_stage_driver_invoked_without_env_mutation(repo: Path) -> None:
    """R10 — freeze path passes driver_invoked to is_driver_invoked without env mutation."""
    prd_dir = repo / "docs/prds/085-prd-demo"
    prd_dir.mkdir(parents=True, exist_ok=True)
    (prd_dir / "prd.md").write_text("---\ntype: prd\n---\n# Demo\n", encoding="utf-8")

    provisioned = provision_doc_run(repo, topic="freeze-driver-param", tier="Standard")
    run_id = str(provisioned["runId"])
    state = _state_with_prd(repo, run_id)

    os.environ.pop("SW_DOC_DRIVER", None)
    seen: list[bool] = []

    def fake_freeze(_root, _artifact, *, owner, driver_invoked, unit_id=None, **kwargs):
        seen.append(is_driver_invoked(driver_invoked))
        return {
            "verdict": "pass",
            "owner": owner,
            "durabilityState": "verified",
            "lifecycleState": "frozen",
            "revision": "rev",
        }

    with patch("check_frozen_lib.freeze_artifact", side_effect=fake_freeze):
        freeze_stage_artifact(repo, state, "freeze-prd")

    assert seen == [True]
    assert os.environ.get("SW_DOC_DRIVER") is None
