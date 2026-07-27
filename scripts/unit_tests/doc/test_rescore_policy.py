"""PRD 081 R17 — final triage rescore policy fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_loop import (
    consume_agent_stage,
    load_doc_state,
    provision_doc_run,
)
from doc_rescore import amendment_input_path, evaluate_rescore


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        with patch("planning_reserve.canonical_repo_root", return_value=repo):
            yield


def test_escalation_proceeds_automatically_and_is_recorded(repo: Path) -> None:
    result = evaluate_rescore(
        current_tier="Standard",
        proposed_tier="Full",
        signals={"file_count": 8},
    )
    assert result["verdict"] == "pass"
    assert result["action"] == "rescore-escalate"
    assert result["appliedTier"] == "Full"
    assert result["receipt"]["automatic"] is True
    assert result["requiresBrainstorm"] is True


def test_downgrade_halts_without_justification(repo: Path) -> None:
    result = evaluate_rescore(
        current_tier="Full",
        proposed_tier="Standard",
    )
    assert result["verdict"] == "fail"
    assert result["error"] == "downgrade-without-justification"
    assert result["halt"] == "doc-loop:rescore-downgrade"


def test_downgrade_allowed_with_human_attribution(repo: Path) -> None:
    result = evaluate_rescore(
        current_tier="Full",
        proposed_tier="Standard",
        justification="Scope narrowed after review",
        actor="operator@example.com",
    )
    assert result["verdict"] == "pass"
    assert result["action"] == "rescore-downgrade"
    assert result["receipt"]["actor"] == "operator@example.com"


def test_post_freeze_signal_recorded_as_amendment_input(repo: Path) -> None:
    result = evaluate_rescore(
        current_tier="Standard",
        proposed_tier="Full",
        frozen=True,
        unit_id="081-prd-demo",
        root=repo,
        signals={"risk_triggers": ["auth"]},
    )
    assert result["verdict"] == "pass"
    assert result["frozenUnitClosed"] is True
    assert result["appliedTier"] == "Standard"
    path = amendment_input_path(repo, "081-prd-demo")
    assert path.is_file()
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["frozenUnitClosed"] is True
    assert payload["signals"]


def test_doc_loop_sequences_rescore_before_freeze_and_escalates(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="rescore-topic", tier="Standard")
    run_id = str(provisioned["runId"])
    state = load_doc_state(repo, run_id)

    for stage in ("triage", "prd", "doc-review"):
        consume_agent_stage(repo, state, stage, outcome={})
        state = load_doc_state(repo, run_id)

    with patch("doc_loop.run_related_work_scan", return_value={"verdict": "ok", "proposals": []}):
        from doc_loop import execute_mechanical_stage

        execute_mechanical_stage(repo, state, "related-work")
    state = load_doc_state(repo, run_id)
    assert state["stage"] == "final-triage-rescore"

    consume_agent_stage(
        repo,
        state,
        "final-triage-rescore",
        outcome={"proposedTier": "Full", "signals": {"file_count": 8}},
    )
    state = load_doc_state(repo, run_id)
    assert state["tier"] == "Full"
    assert state["stage"] == "brainstorm"
    assert state["rescoreReceipt"]["direction"] == "escalate"


def test_doc_loop_halts_on_unjustified_downgrade(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="downgrade-topic", tier="Full")
    run_id = str(provisioned["runId"])
    state = load_doc_state(repo, run_id)
    state["stage"] = "final-triage-rescore"
    state["nextAction"] = "final-triage-rescore"
    from doc_loop import save_doc_state

    save_doc_state(repo, state)

    result = consume_agent_stage(
        repo,
        state,
        "final-triage-rescore",
        outcome={"proposedTier": "Standard"},
    )
    assert result.get("halted") is True
    halted = load_doc_state(repo, run_id)
    assert halted["verdict"] == "halted"
    assert halted["halt"] == "doc-loop:rescore-downgrade"
