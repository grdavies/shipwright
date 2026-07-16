"""PRD 070 phase 8 — abandoned / closed-unmerged delivery surfacing tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc


def _write_state(root: Path, slug: str, state: dict) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / f"sw-deliver-state.{slug}.json").write_text(json.dumps(state), encoding="utf-8")


def test_abandoned_closed_unmerged_is_surfaced(tmp_path: Path) -> None:
    state = {
        "target": {"slug": "automated-delivery-closeout", "branch": "feat/automated-delivery-closeout"},
        "completion": {"status": "completed-pending-merge"},
        "terminalPr": {"number": 9001},
    }
    _write_state(tmp_path, "automated-delivery-closeout", state)

    def probe(_root: Path, number: int) -> dict:
        assert number == 9001
        return {"verdict": "ok", "state": "CLOSED"}

    result = dc.reconcile_abandoned_deliveries(tmp_path, pr_probe=probe)
    assert result["verdict"] == "surface"
    assert result["operatorDecisionRequired"] is True
    assert result["surfaced"][0]["prNumber"] == 9001
    assert "operator decision required" in result["resumeCommand"]


def test_merged_terminal_pr_not_surfaced(tmp_path: Path) -> None:
    state = {
        "target": {"slug": "automated-delivery-closeout", "branch": "feat/automated-delivery-closeout"},
        "completion": {"status": "completed-pending-merge"},
        "terminalPr": {"number": 42},
    }
    _write_state(tmp_path, "automated-delivery-closeout", state)

    result = dc.reconcile_abandoned_deliveries(
        tmp_path,
        pr_probe=lambda _r, _n: {"verdict": "ok", "state": "MERGED"},
    )
    assert result["verdict"] == "noop"


def test_non_pending_merge_not_surfaced(tmp_path: Path) -> None:
    state = {
        "target": {"slug": "automated-delivery-closeout", "branch": "feat/automated-delivery-closeout"},
        "completion": {"status": "running"},
        "terminalPr": {"number": 9001},
    }
    _write_state(tmp_path, "automated-delivery-closeout", state)

    result = dc.reconcile_abandoned_deliveries(
        tmp_path,
        pr_probe=lambda _r, _n: {"verdict": "ok", "state": "CLOSED"},
    )
    assert result["verdict"] == "noop"
