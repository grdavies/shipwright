"""PRD 337 R13 — pending-merge must not mask in-progress docs currency."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc


def _pending_merge_state(**overrides) -> dict:
    state = {
        "prd_number": "337",
        "target": {"slug": "workflow-runtime-autonomy-lifecycle", "branch": "feat/workflow-runtime-autonomy-lifecycle"},
        "phases": {
            "1": {"slug": "phase-one", "status": "green-merged"},
            "2": {"slug": "phase-two", "status": "green-merged"},
        },
        "completion": {"status": "completed-pending-merge"},
        "terminalPr": {"number": 932},
    }
    state.update(overrides)
    return state


def test_pending_merge_docs_currency_in_progress_cannot_report_complete() -> None:
    """B/I — pending-merge with in-flight docs currency stays incomplete."""
    state = _pending_merge_state(docsCurrency={"status": "in-progress"})
    assessment = dc.assess_docs_currency_terminal_state(ROOT, state)
    assert assessment["docsCurrencyComplete"] is False
    assert assessment["indexStatus"] == "in-progress"
    assert assessment["maskedByPendingMerge"] is True
    assert assessment["verdict"] == "in-progress"


def test_missing_docs_state_uses_index_evidence(tmp_path: Path) -> None:
    """Z — absent docsCurrency block defers to projected INDEX evidence."""
    state = _pending_merge_state()
    with patch(
        "wave_living_docs.read_index_status_evidence",
        return_value={"status": "in-progress"},
    ):
        assert dc.docs_currency_phase_in_progress(state, root=tmp_path) is True
        assert dc.derive_closeout_index_status(state, root=tmp_path) == "in-progress"
        assert dc.docs_currency_terminal_ready(state, root=tmp_path) is False


def test_one_phase_terminal_without_docs_block_is_complete(tmp_path: Path) -> None:
    """O — single green phase + pending-merge without in-progress signal is complete."""
    state = _pending_merge_state(
        phases={"1": {"slug": "only-phase", "status": "green-merged"}},
    )
    with patch("wave_living_docs.read_index_status_evidence", return_value=None):
        assert dc.derive_closeout_index_status(state, root=tmp_path) == "complete"
        assert dc.docs_currency_terminal_ready(state, root=tmp_path) is True


def test_multiple_state_signals_prefer_in_progress(tmp_path: Path) -> None:
    """M — explicit docsCurrency and gate failure both block completion."""
    state = _pending_merge_state(
        docsCurrency={"status": "pending", "complete": False},
        docsCurrencyGate={"verdict": "fail"},
    )
    assessment = dc.assess_docs_currency_terminal_state(tmp_path, state)
    assert assessment["docsCurrencyComplete"] is False
    assert assessment["docsCurrencyInProgress"] is True


def test_merged_to_main_boundary_stays_complete() -> None:
    """B — merged-to-main always derives complete regardless of docs currency."""
    state = _pending_merge_state(docsCurrency={"status": "in-progress"})
    assert dc.derive_closeout_index_status(state, merged_to_main=True) == "complete"


def test_index_contract_matches_derived_status(tmp_path: Path) -> None:
    """I — assess payload indexStatus matches derive_closeout_index_status."""
    state = _pending_merge_state(docsCurrency={"complete": False})
    derived = dc.derive_closeout_index_status(state, root=tmp_path)
    assessment = dc.assess_docs_currency_terminal_state(tmp_path, state)
    assert assessment["indexStatus"] == derived
    assert assessment["rawIndexStatus"] == "complete"


def test_inconsistent_gate_verdict_blocks_complete() -> None:
    """E — non-pass docsCurrencyGate refuses complete even when phases are green."""
    state = _pending_merge_state(docsCurrencyGate={"verdict": "blocked"})
    assert dc.docs_currency_terminal_ready(state) is False


def test_corrected_derivation_after_docs_currency_passes(tmp_path: Path) -> None:
    """S — once docs currency is complete, pending-merge no longer masks."""
    state = _pending_merge_state(
        docsCurrency={"status": "complete", "complete": True},
        docsCurrencyGate={"verdict": "pass"},
    )
    with patch("wave_living_docs.read_index_status_evidence", return_value={"status": "complete"}):
        assessment = dc.assess_docs_currency_terminal_state(tmp_path, state)
        assert assessment["docsCurrencyComplete"] is True
        assert assessment["maskedByPendingMerge"] is False
        assert assessment["verdict"] == "pass"
