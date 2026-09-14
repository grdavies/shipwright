"""PRD 352 Slice 3 — spending and retry boundaries (R22–R25, SC-C)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "scripts")]

from handoff.transition import (  # noqa: E402
    TransitionError,
    create_transition,
    load_transition,
    record_observed_failure,
)
from handoff_bundle import (  # noqa: E402
    check_switch_retry_bounds,
    enforce_spending_policy_on_fallback,
    emit_spending_policy_halt,
    guard_host_switch,
    load_host_switch_config,
    read_host_switch_retry_state,
    record_host_switch_attempt,
)


def _write_workflow_config(root: Path, switch: dict) -> None:
    cfg_dir = root / ".cursor"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "workflow.config.json").write_text(
        json.dumps({"host": {"provider": "none", "switch": switch}}) + "\n",
        encoding="utf-8",
    )


def test_r22_blocks_unauthorized_automatic_fallback(tmp_path: Path) -> None:
    _write_workflow_config(tmp_path, {"spendingPolicy": {}})
    halt = enforce_spending_policy_on_fallback(
        tmp_path,
        destination_host="claude-code",
        observation={"source": "injection", "code": "subscription_exhausted", "message": "quota exhausted"},
    )
    assert halt is not None
    assert halt["verdict"] == "halt"
    assert halt["error"] == "handoff:spending-policy-violation"
    assert "authorization" in halt["constraint"]


def test_r22_authorized_destination_allows_fallback(tmp_path: Path) -> None:
    _write_workflow_config(
        tmp_path,
        {
            "spendingPolicy": {
                "authorizedDestinations": ["claude-code"],
            }
        },
    )
    halt = enforce_spending_policy_on_fallback(
        tmp_path,
        destination_host="claude-code",
        observation={"source": "injection", "code": "host-unavailable", "message": "host down"},
    )
    assert halt is None


def test_r22_subscription_exhaustion_blocks_paid_fallback(tmp_path: Path) -> None:
    _write_workflow_config(
        tmp_path,
        {
            "spendingPolicy": {
                "authorizedDestinations": ["claude-code"],
                "allowPaidFallback": False,
            }
        },
    )
    halt = enforce_spending_policy_on_fallback(
        tmp_path,
        destination_host="claude-code",
        observation={"source": "injection", "code": "subscription_exhausted", "message": "no quota"},
        destination_model="claude-opus-5-thinking-high",
    )
    assert halt is not None
    assert "paid" in halt["constraint"].lower() or "subscription" in halt["constraint"].lower()
    assert halt["alternatives"]


def test_r23_records_observed_failure_without_fabrication(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-spend", run_id="run-1", session_id="sess-1")
    record_observed_failure(
        tmp_path,
        "tid-spend",
        {"source": "injection", "code": "subscription_exhausted", "message": "quota exhausted"},
    )
    record = load_transition(tmp_path, "tid-spend")
    assert record["spendingObservation"]["code"] == "subscription_exhausted"
    assert "remainingAllowance" not in record["spendingObservation"]
    assert "resetAt" not in record["spendingObservation"]


def test_r23_rejects_fabricated_allowance(tmp_path: Path) -> None:
    create_transition(tmp_path, transition_id="tid-fab", run_id="run-1", session_id="sess-1")
    with pytest.raises(TransitionError) as exc:
        record_observed_failure(
            tmp_path,
            "tid-fab",
            {"source": "injection", "code": "quota", "remainingAllowance": 42},
        )
    assert exc.value.code == "transition_failure_fabrication"


def test_r24_cooldown_blocks_rapid_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_workflow_config(tmp_path, {"maxRetries": 3, "cooldownSeconds": 300})
    now = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
    record_host_switch_attempt(
        tmp_path,
        "run-cooldown",
        source_host="cursor",
        destination_host="claude-code",
        now=now,
    )
    halt = check_switch_retry_bounds(
        tmp_path,
        "run-cooldown",
        now=now + timedelta(seconds=30),
    )
    assert halt is not None
    assert halt["constraint"] == "host.switch.cooldownSeconds=300"


def test_r24_max_retries_blocks_repeated_switch(tmp_path: Path) -> None:
    _write_workflow_config(tmp_path, {"maxRetries": 2, "cooldownSeconds": 0})
    base = datetime(2026, 9, 14, 12, 0, 0, tzinfo=timezone.utc)
    for offset in (0, 400):
        record_host_switch_attempt(
            tmp_path,
            "run-max",
            source_host="cursor",
            destination_host="claude-code",
            now=base + timedelta(seconds=offset),
        )
    halt = check_switch_retry_bounds(tmp_path, "run-max", now=base + timedelta(seconds=800))
    assert halt is not None
    assert halt["constraint"] == "host.switch.maxRetries=2"


def test_r25_emits_typed_halt_with_alternatives() -> None:
    halt = emit_spending_policy_halt(
        constraint="automatic fallback requires prior authorization",
        alternatives=["wait", "authorize destination"],
        destination_host="claude-code",
    )
    assert halt["verdict"] == "halt"
    assert halt["halt"] == "handoff:spending-policy-violation"
    assert halt["constraint"]
    assert len(halt["alternatives"]) >= 2


def test_sc_c_injection_guard_host_switch_records_attempt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_workflow_config(
        tmp_path,
        {
            "maxRetries": 5,
            "cooldownSeconds": 0,
            "spendingPolicy": {"authorizedDestinations": ["claude-code"]},
        },
    )
    monkeypatch.setenv("SW_HOST_SWITCH_USER_INSTRUCTION", "operator approved switch")
    result = guard_host_switch(
        tmp_path,
        run_id="run-sc-c",
        source_host="cursor",
        destination_host="claude-code",
        transition_id="tid-sc-c",
        record_attempt=True,
    )
    assert result is None
    state = read_host_switch_retry_state(tmp_path, "run-sc-c")
    assert len(state["attempts"]) == 1
    assert load_host_switch_config(tmp_path)["maxRetries"] == 5
