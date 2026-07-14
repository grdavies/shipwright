"""PRD 067 Wave A (R1–R9) reliability regressions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest


def test_tasks_unit_id_candidates_include_debug_forms() -> None:
    from planning_store import _tasks_unit_id_candidates

    cands = _tasks_unit_id_candidates("067-prd-operator-surface-reliability-craft-ux", "067")
    assert "tasks-067-operator-surface-reliability-craft-ux" in cands
    assert "tasks-debug-operator-surface-reliability-craft-ux" in cands
    assert "tasks-debug-067-operator-surface-reliability-craft-ux" in cands


def test_ship_lease_reclaim_requires_same_host_and_dead_pid(tmp_path: Path) -> None:
    from wave_lock import reclaim_stale_ship_lease, lock_host, utc_now, SHIP_LEASE_STALE_SECONDS

    lock = tmp_path / "lease.lock"
    # Foreign host — never reclaim
    meta = {
        "pid": 999999,
        "host": "other-host",
        "heartbeatAt": "2000-01-01T00:00:00Z",
        "acquiredAt": "2000-01-01T00:00:00Z",
    }
    lock.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    assert reclaim_stale_ship_lease(lock) is False
    assert lock.is_file()

    # Same host + stale + dead pid — reclaim
    meta["host"] = lock_host()
    lock.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    assert reclaim_stale_ship_lease(lock) is True
    assert not lock.is_file()


def test_clear_phase_env_strips_sw_phase(monkeypatch: pytest.MonkeyPatch) -> None:
    import wave_terminal as wt

    monkeypatch.setenv("SW_PHASE_MODE", "1")
    monkeypatch.setenv("SW_PHASE_SLUG", "wave-a")
    monkeypatch.setenv("SW_OTHER", "keep")
    saved = wt.clear_phase_env()
    assert "SW_PHASE_MODE" not in os.environ
    assert "SW_PHASE_SLUG" not in os.environ
    assert os.environ.get("SW_OTHER") == "keep"
    wt.restore_phase_env(saved)
    assert os.environ.get("SW_PHASE_MODE") == "1"


def test_preflight_timeout_default_90(tmp_path: Path) -> None:
    from wave_deliver import preflight_timeout_seconds

    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "deliver": {}}), encoding="utf-8"
    )
    assert preflight_timeout_seconds(tmp_path) == 90
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"version": 1, "deliver": {"preflight": {"timeoutSeconds": 12}}}),
        encoding="utf-8",
    )
    assert preflight_timeout_seconds(tmp_path) == 12


def test_resolve_currency_check_prefers_materialized(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import wave_deliver_loop as wdl

    logical = "docs/prds/067-x/tasks-067-x.md"
    mat = tmp_path / ".cursor" / "planning-materialized" / logical
    mat.parent.mkdir(parents=True, exist_ok=True)
    mat.write_text("# tasks\n", encoding="utf-8")

    monkeypatch.setattr(
        "planning_materialize.ensure_run_entry_materialized",
        lambda *a, **k: {"verdict": "ok"},
    )
    monkeypatch.setattr(
        "planning_path_redirect.resolve_readable_path",
        lambda root, rel: (str(mat.relative_to(root)), mat),
    )
    monkeypatch.setattr(wdl, "orchestrator_worktree_path", lambda root, state: None)
    root, rel = wdl.resolve_currency_check(
        tmp_path, {"source_task_list": logical}, {}
    )
    assert root == tmp_path
    assert "planning-materialized" in rel
