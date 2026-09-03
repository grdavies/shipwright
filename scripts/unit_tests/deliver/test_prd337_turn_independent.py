"""PRD 337 R6 — inline ship turn-independent continuation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import (  # noqa: E402
    clear_ship_loop_await,
    compute_next_action,
    execute_dispatch_ship,
    persist_ship_loop_await,
    ship_loop_await_for_phase,
    utc_now,
)


@pytest.fixture(autouse=True)
def shipwright_scripts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(SCRIPT_DIR.resolve()))
    monkeypatch.delenv("SW_DELIVER_RUN_ID", raising=False)
    monkeypatch.delenv("SW_RUN_ID", raising=False)


def _base_state(*, slug: str = "inline-demo", phase_id: str = "2") -> dict:
    return {
        "verdict": "running",
        "runId": "deliver-test-inline",
        "source_task_list": "docs/prds/337-inline/tasks.md",
        "target": {"branch": "feat/inline-demo"},
        "phases": {
            phase_id: {
                "status": "in-flight",
                "slug": slug,
                "branch": f"feat/inline-demo-phase-{slug}",
                "inlineDispatchedAt": utc_now(),
            }
        },
        "phaseWorktrees": {
            phase_id: {"path": "/tmp/phase-wt", "name": f"{slug}-wt"},
        },
    }


def _plan(slug: str = "inline-demo", phase_id: str = "2") -> dict:
    return {
        "mode": "phase",
        "target": {"branch": "feat/inline-demo"},
        "waves": [[phase_id]],
        "items": [{"id": phase_id, "slug": slug}],
    }


def test_turn_independent_inline_ship_single_invocation(
    repo_root: Path,
) -> None:
    """O — one dispatch-ship invocation drains to shipComplete without chat turn."""
    state = _base_state()
    plan = _plan()
    step = {"phaseId": "2", "phaseSlug": "inline-demo"}
    complete_drive = {
        "verdict": "pass",
        "complete": True,
        "action": "ship-loop-drive",
        "phase": "inline-demo",
    }

    with (
        patch("wave_deliver_loop.acquire_inline_dispatch_lease", return_value=(0, {})),
        patch("wave_deliver_loop.mark_phases_in_flight"),
        patch(
            "wave_deliver_loop._ensure_phase_worktree_for_dispatch",
            return_value=repo_root,
        ),
        patch(
            "wave_deliver_loop._resolve_ship_scripts_root",
            return_value=SCRIPT_DIR,
        ),
        patch("wave_deliver_loop.run_ship_loop_drive", return_value=(0, complete_drive)),
        patch("wave_deliver_loop.save_state") as save_state,
    ):
        result = execute_dispatch_ship(repo_root, state, step)

    assert result.get("shipComplete") is True
    assert result.get("awaitAgent") is not True
    assert ship_loop_await_for_phase(state, "2") is None
    save_state.assert_called()


def test_turn_independent_inline_ship_process_boundary_resume(
    repo_root: Path,
) -> None:
    """B/S — persisted shipLoopAwait resumes dispatch-ship after process boundary."""
    state = _base_state()
    plan = _plan()
    persist_ship_loop_await(
        state,
        "2",
        "inline-demo",
        {"step": "sw-execute", "contract": {"step": "sw-execute"}},
    )
    step = {"phaseId": "2", "phaseSlug": "inline-demo"}
    consumed = {"verdict": "pass", "action": "consume-outcome", "step": "sw-execute"}
    complete_drive = {
        "verdict": "pass",
        "complete": True,
        "action": "ship-loop-drive",
        "phase": "inline-demo",
    }

    with (
        patch("wave_deliver_loop.acquire_inline_dispatch_lease", return_value=(0, {})),
        patch("wave_deliver_loop.mark_phases_in_flight"),
        patch(
            "wave_deliver_loop._ensure_phase_worktree_for_dispatch",
            return_value=repo_root,
        ),
        patch(
            "wave_deliver_loop._resolve_ship_scripts_root",
            return_value=SCRIPT_DIR,
        ),
        patch(
            "wave_deliver_loop.run_ship_loop_consume_outcome",
            return_value=(0, consumed),
        ),
        patch(
            "wave_deliver_loop.run_ship_loop_drive",
            return_value=(0, complete_drive),
        ),
        patch("wave_deliver_loop.save_state"),
    ):
        result = execute_dispatch_ship(repo_root, state, step)

    assert result.get("shipComplete") is True
    assert ship_loop_await_for_phase(state, "2") is None
    assert any(
        entry.get("action") == "consume-outcome" for entry in result.get("shipLoopHistory", [])
    )


def test_turn_independent_inline_ship_compute_next_resumes_await(
    repo_root: Path,
) -> None:
    """E — compute_next_action returns dispatch-ship while shipLoopAwait is live."""
    state = _base_state()
    plan = _plan()
    persist_ship_loop_await(
        state,
        "2",
        "inline-demo",
        {"step": "sw-execute", "contract": {}},
    )
    state["baseCapture"] = {"head": "abc"}
    state["targetLock"] = {"branch": "feat/inline-demo"}
    state["currentWave"] = 1
    state["orchestratorWorktree"] = {"path": str(repo_root)}
    state["specSeed"] = {"done": True}

    with (
        patch("wave_deliver_loop.check_budget_halt", return_value=None),
        patch("wave_deliver_loop.check_deliver_hang_desync", return_value=None),
        patch("wave_deliver_loop.trunk_base_persisted", return_value=True),
        patch("wave_deliver_loop.inline_dispatch_lease_held_live", return_value=True),
        patch(
            "wave_deliver_loop.read_phase_status_optional",
            return_value=(None, None),
        ),
        patch("wave_deliver_loop.phase_worktree_provisioned", return_value=True),
        patch("wave_deliver_loop.needs_phase_plan_proposal", return_value=False),
    ):
        nxt = compute_next_action(repo_root, state, plan)

    assert nxt.get("action") == "dispatch-ship"
    assert nxt.get("phaseId") == "2"
    assert "shipLoopAwait" in (nxt.get("note") or "")


def test_turn_independent_inline_ship_await_agent_persists(
    repo_root: Path,
) -> None:
    """I — awaitAgent persists shipLoopAwait for durable resume."""
    state = _base_state()
    step = {"phaseId": "2", "phaseSlug": "inline-demo"}
    await_drive = {
        "verdict": "pass",
        "awaitAgent": True,
        "step": "sw-execute",
        "contract": {"artifact": "execute-integrate.status.json"},
    }

    with (
        patch("wave_deliver_loop.acquire_inline_dispatch_lease", return_value=(0, {})),
        patch("wave_deliver_loop.mark_phases_in_flight"),
        patch(
            "wave_deliver_loop._ensure_phase_worktree_for_dispatch",
            return_value=repo_root,
        ),
        patch(
            "wave_deliver_loop._resolve_ship_scripts_root",
            return_value=SCRIPT_DIR,
        ),
        patch("wave_deliver_loop.run_ship_loop_drive", return_value=(0, await_drive)),
        patch("wave_deliver_loop.save_state") as save_state,
    ):
        result = execute_dispatch_ship(repo_root, state, step)

    assert result.get("awaitAgent") is True
    pending = ship_loop_await_for_phase(state, "2")
    assert pending is not None
    assert pending.get("step") == "sw-execute"
    save_state.assert_called()
    clear_ship_loop_await(state, "2")
    assert ship_loop_await_for_phase(state, "2") is None
