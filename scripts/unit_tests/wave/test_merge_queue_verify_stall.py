"""PRD 072 R5 — merge-queue liveness refresh + drain decoupling from verify stalls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from wave_deliver_loop import (
    check_watchdog,
    compute_next_action,
    merge_queue_drain_preferred,
    refresh_merge_queue_liveness_cas,
)
from wave_merge import should_defer_post_merge_verify


def _plan() -> dict[str, Any]:
    return {
        "mode": "phase",
        "target": {"branch": "feat/demo", "slug": "demo"},
        "items": [
            {"id": "1", "slug": "alpha", "branch": "feat/demo-phase-alpha"},
            {"id": "2", "slug": "beta", "branch": "feat/demo-phase-beta"},
        ],
        "waves": [["1", "2"]],
        "edges": [],
    }


def _base_state() -> dict[str, Any]:
    return {
        "verdict": "running",
        "target": {"branch": "feat/demo", "slug": "demo"},
        "nextAction": "merge-run-next",
        "currentWave": 1,
        "baseCapture": {"branch": "main", "sha": "abc"},
        "waveBatchingPlan": {"waves": [["1", "2"]]},
        "mergeQueue": [
            {"phaseSlug": "beta", "head": "def", "pr": 2},
        ],
        "mergeJournal": None,
        "phases": {
            "1": {
                "slug": "alpha",
                "status": "teardown-pending",
                "branch": "feat/demo-phase-alpha",
                "startedAt": "2026-01-01T00:00:00Z",
                "cause": "verify:environmental",
                "verifyEnvironmental": True,
                "postMergeVerifyPending": True,
            },
            "2": {
                "slug": "beta",
                "status": "in-flight",
                "branch": "feat/demo-phase-beta",
                "startedAt": "2026-01-01T00:00:00Z",
            },
        },
        "verifyRemediationAttempts": {"1": 1},
        "orchestratorWorktree": {"path": "/tmp/orch"},
        "updatedAt": "2026-06-01T12:00:00Z",
        "driverHeartbeatAt": "2099-01-01T00:00:00Z",
    }


def test_merge_queue_drain_preferred_when_queue_non_empty() -> None:
    state = _base_state()
    assert merge_queue_drain_preferred(state) is True
    state["mergeJournal"] = {"phase": "alpha"}
    assert merge_queue_drain_preferred(state) is False


def test_should_defer_post_merge_verify_when_siblings_queued() -> None:
    state = _base_state()
    assert should_defer_post_merge_verify(state) is True
    state["mergeQueue"] = []
    assert should_defer_post_merge_verify(state) is False


def test_environmental_blocked_defers_remediate_when_queue_drains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _base_state()
    state["phases"]["1"]["status"] = "blocked"
    plan = _plan()
    root = Path(__file__).resolve().parents[3]
    monkeypatch.chdir(root)
    monkeypatch.setattr(
        "wave_deliver_loop.trunk_base_persisted",
        lambda _root: True,
    )
    monkeypatch.setattr(
        "wave_deliver_loop.remediation_max",
        lambda _root: 2,
    )
    monkeypatch.setattr(
        "wave_deliver_loop.load_state",
        lambda _root, task_list=None: json.loads(json.dumps(state)),
    )
    monkeypatch.setattr(
        "wave_deliver_loop.save_state",
        lambda _root, payload: state.update(payload),
    )
    next_step = compute_next_action(root, state, plan)
    assert next_step["action"] == "merge-run-next"


def test_refresh_liveness_preserves_started_at(tmp_path: Path) -> None:
    state = _base_state()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")

    def _load(_root: Path, task_list: str | None = None) -> dict[str, Any]:
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _save(_root: Path, payload: dict[str, Any]) -> None:
        state_path.write_text(json.dumps(payload), encoding="utf-8")

    with patch("wave_deliver_loop.load_state", _load), patch(
        "wave_deliver_loop.save_state", _save
    ):
        assert refresh_merge_queue_liveness_cas(tmp_path, state) is True
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        beta = saved["phases"]["2"]
        assert beta["startedAt"] == "2026-01-01T00:00:00Z"
        assert beta.get("livenessAt")
        assert beta.get("updatedAt")


def test_refresh_liveness_cas_retries_on_conflict(tmp_path: Path) -> None:
    state = _base_state()
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    calls = {"n": 0}

    def _load(_root: Path, task_list: str | None = None) -> dict[str, Any]:
        calls["n"] += 1
        data = json.loads(state_path.read_text(encoding="utf-8"))
        if calls["n"] == 1:
            data["updatedAt"] = "2026-06-01T12:00:01Z"
            state_path.write_text(json.dumps(data), encoding="utf-8")
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _save(_root: Path, payload: dict[str, Any]) -> None:
        state_path.write_text(json.dumps(payload), encoding="utf-8")

    with patch("wave_deliver_loop.load_state", _load), patch(
        "wave_deliver_loop.save_state", _save
    ):
        assert refresh_merge_queue_liveness_cas(tmp_path, state) is True
        assert calls["n"] >= 2


def test_watchdog_respects_recent_liveness_at(tmp_path: Path) -> None:
    state = _base_state()
    state["phases"]["2"]["startedAt"] = "2020-01-01T00:00:00Z"
    state["phases"]["2"]["livenessAt"] = "2099-01-01T00:00:00Z"
    assert check_watchdog(tmp_path, state) is None


def test_watchdog_trips_hung_phase_without_liveness(tmp_path: Path) -> None:
    state = _base_state()
    state["phases"]["2"]["startedAt"] = "2020-01-01T00:00:00Z"
    state["phases"]["2"].pop("livenessAt", None)
    state["phases"]["2"].pop("updatedAt", None)
    state.pop("driverHeartbeatAt", None)
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("wave_deliver_loop.phase_timeout_minutes", lambda _root: 1)
    monkeypatch.setattr("wave_deliver_loop.age_seconds", lambda ts: 999999.0)
    try:
        cause = check_watchdog(tmp_path, state)
    finally:
        monkeypatch.undo()
    assert cause == "phase-timeout:2"


def test_post_merge_verify_remediate_when_queue_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _base_state()
    state["mergeQueue"] = []
    state["phases"]["1"]["status"] = "blocked"
    plan = _plan()
    monkeypatch.setattr("wave_deliver_loop.trunk_base_persisted", lambda _root: True)
    monkeypatch.setattr("wave_deliver_loop.remediation_max", lambda _root: 2)
    next_step = compute_next_action(tmp_path, state, plan)
    assert next_step["action"] == "post-merge-verify-remediate"
    assert next_step["causeClass"] == "environmental"
