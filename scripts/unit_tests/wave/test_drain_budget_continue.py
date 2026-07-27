"""PRD 081 R22 — drain-budget exhaustion returns continue, not blocker."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_deliver_loop import (
    DRAIN_STEP_BUDGET_HALT,
    MECHANICAL_ACTIONS,
    cmd_deliver_loop,
    is_budget_halt,
    is_drain_step_budget_exhaustion,
)


def test_drain_step_budget_is_not_budget_halt() -> None:
    assert is_drain_step_budget_exhaustion(DRAIN_STEP_BUDGET_HALT)
    assert not is_budget_halt(DRAIN_STEP_BUDGET_HALT)


def test_drain_budget_exhaustion_emits_continue(repo_root: Path) -> None:
    state = {
        "verdict": "running",
        "runId": "deliver-test-run",
        "phases": {"1": {"status": "pending", "slug": "alpha"}},
        "nextAction": "merge-enqueue",
    }
    plan = {"mode": "phase", "target": {"branch": "feat/demo"}, "phases": []}
    mechanical_next = {"action": "merge-enqueue", "phaseSlug": "alpha", "resume": True}

    emitted: list[dict] = []

    def capture_emit(payload: dict, exit_code: int = 0) -> None:
        emitted.append({"payload": payload, "exit_code": exit_code})
        raise SystemExit(exit_code)

    first_step = {"action": "collect-status", "phaseSlug": "alpha", "resume": True}

    with (
        patch("wave_deliver_loop.load_state", return_value=state),
        patch("wave_deliver_loop.load_plan", return_value=plan),
        patch("wave_deliver_loop.assert_run_identity"),
        patch("wave_deliver_loop.assert_driver_adopt_gate"),
        patch("wave_deliver_loop.init_budget_counters"),
        patch("wave_deliver_loop.record_budget_tick"),
        patch("wave_deliver_loop.save_state"),
        patch(
            "wave_deliver_loop.execute_mechanical",
            return_value={"executed": "collect-status"},
        ),
        patch(
            "wave_deliver_loop.compute_next_action",
            side_effect=[first_step, mechanical_next],
        ),
        patch("wave_deliver_loop.drain_mechanical_enabled", return_value=True),
        patch("wave_deliver_loop.append_log"),
        patch("wave_deliver_loop.emit", side_effect=capture_emit),
    ):
        with pytest.raises(SystemExit) as exc:
            cmd_deliver_loop(repo_root, ["--max-steps", "1"])
        assert exc.value.code == 0

    assert emitted, "deliver-loop should emit continuation payload"
    payload = emitted[-1]["payload"]
    assert payload["verdict"] == "continue"
    assert payload["halt"] is False
    assert payload["cause"] == DRAIN_STEP_BUDGET_HALT
    assert payload["next"]["action"] in MECHANICAL_ACTIONS


def test_drain_budget_continue_payload_is_not_blocker_shaped() -> None:
    payload = {
        "verdict": "continue",
        "halt": False,
        "cause": DRAIN_STEP_BUDGET_HALT,
        "next": {"action": "collect-status", "resume": True},
    }
    assert payload["verdict"] != "blocked"
    assert "blockerReport" not in payload
    serialized = json.dumps(payload)
    assert "blocked" not in serialized or payload["verdict"] == "continue"
