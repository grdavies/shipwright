"""PRD 073 phase 1 — merge enqueue queue retained across mechanical persist (R8, R9, R13)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_deliver_loop import execute_mechanical, load_state, save_state

pytestmark = [pytest.mark.git]

_ALPHA_QUEUE = [
    {
        "phaseSlug": "alpha",
        "head": "deadbeef00000000000000000000000000000000",
        "pr": 42,
        "enqueuedAt": "2026-01-01T00:00:00Z",
    }
]

_BETA_QUEUE = [
    *_ALPHA_QUEUE,
    {
        "phaseSlug": "beta",
        "head": "cafebabe00000000000000000000000000000000",
        "pr": 43,
        "enqueuedAt": "2026-01-01T00:00:01Z",
    },
]


def _seed_state(tmp_git_repo: Path) -> dict:
    state = {
        "verdict": "running",
        "target": {"branch": "feat/demo"},
        "phases": {
            "1": {"id": "1", "slug": "alpha", "status": "in-flight", "branch": "feat/demo-phase-alpha"},
            "2": {"id": "2", "slug": "beta", "status": "in-flight", "branch": "feat/demo-phase-beta"},
        },
        "mergeQueue": [],
        "nextAction": "merge-enqueue",
    }
    cursor = tmp_git_repo / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps({"review": {"provider": "none"}, "checks": {"treatNeutralAsPass": True}}),
        encoding="utf-8",
    )
    save_state(tmp_git_repo, state)
    return state


def _queue_on_disk(root: Path) -> list[dict]:
    return list(load_state(root).get("mergeQueue") or [])


def test_merge_enqueue_mechanical_retains_queue_after_persist(tmp_git_repo: Path) -> None:
    """Stale in-memory state must not wipe mergeQueue on persist_cursor (R8/R9)."""
    state = _seed_state(tmp_git_repo)
    plan = {"target": {"branch": "feat/demo"}}
    step = {"action": "merge-enqueue", "phaseSlug": "alpha"}

    def fake_run_wave(_root: Path, domain: str, cmd: str, *args: str) -> tuple[int, dict]:
        assert domain == "merge" and cmd == "enqueue"
        return 0, {"verdict": "pass", "action": "merge-enqueue", "mergeQueue": _ALPHA_QUEUE}

    with patch("wave_deliver_loop.run_wave", side_effect=fake_run_wave):
        result = execute_mechanical(tmp_git_repo, state, plan, step)

    assert result["executed"] == "merge-enqueue"
    assert _queue_on_disk(tmp_git_repo) == _ALPHA_QUEUE
    assert state.get("nextAction") == "merge-run-next"


def test_collect_all_ready_retains_queue_through_drain(tmp_git_repo: Path) -> None:
    """collect-all-ready applies each enqueue response before a single persist (R8/R9)."""
    state = _seed_state(tmp_git_repo)
    plan = {"target": {"branch": "feat/demo"}}
    step = {
        "action": "collect-all-ready",
        "phases": [{"phaseSlug": "alpha"}, {"phaseSlug": "beta"}],
    }
    calls: list[str] = []

    def fake_run_wave(_root: Path, domain: str, cmd: str, *args: str) -> tuple[int, dict]:
        assert domain == "merge" and cmd == "enqueue"
        slug = args[args.index("--phase-slug") + 1]
        calls.append(slug)
        queue = _ALPHA_QUEUE if slug == "alpha" else _BETA_QUEUE
        return 0, {"verdict": "pass", "action": "merge-enqueue", "mergeQueue": queue}

    with patch("wave_deliver_loop.run_wave", side_effect=fake_run_wave):
        result = execute_mechanical(tmp_git_repo, state, plan, step)

    assert result["executed"] == "collect-all-ready"
    assert calls == ["alpha", "beta"]
    assert _queue_on_disk(tmp_git_repo) == _BETA_QUEUE


def test_apply_merge_enqueue_result_ignores_missing_queue() -> None:
    from wave_deliver_loop import apply_merge_enqueue_result

    state: dict = {"mergeQueue": [{"phaseSlug": "keep"}]}
    apply_merge_enqueue_result(state, {"verdict": "pass"})
    assert state["mergeQueue"] == [{"phaseSlug": "keep"}]
