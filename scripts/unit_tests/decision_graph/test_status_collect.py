#!/usr/bin/env python3
"""Decision frontier status collector unit tests (PRD 280 R20)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.journal import DecisionRunJournal  # noqa: E402
from decision_graph.receipt import build_receipt_envelope  # noqa: E402
from decision_graph.schema import NodeKind, minimal_fixture_graph  # noqa: E402
from status_collect import collect_decision_frontier_summary  # noqa: E402


def _write_graph(root: Path, unit_id: str, document: dict) -> Path:
    path = root / ".cursor" / "sw-decision-graphs" / f"{unit_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def test_no_graph_fails_closed(tmp_path: Path) -> None:
    result = collect_decision_frontier_summary(tmp_path, "missing-unit")
    assert result["verdict"] == "fail"
    assert result["readyCount"] == 0


def test_ready_count_one(tmp_path: Path) -> None:
    unit_id = "tasks-280-engineering-decision-layer"
    doc = minimal_fixture_graph()
    doc["spec"]["nodes"] = [
        {"id": "d1", "kind": NodeKind.DECISION.value, "status": "open", "question": "Q?"},
    ]
    _write_graph(tmp_path, unit_id, doc)
    result = collect_decision_frontier_summary(tmp_path, unit_id)
    assert result["verdict"] == "pass"
    assert result["readyCount"] == 1
    assert result["blockedHumanActions"] == []


def test_blocked_human_action_without_receipt(tmp_path: Path) -> None:
    unit_id = "tasks-280-engineering-decision-layer"
    doc = minimal_fixture_graph()
    doc["spec"]["nodes"] = [
        {
            "id": "human",
            "kind": NodeKind.HUMAN_ACTION.value,
            "status": "open",
            "title": "Approve",
        },
        {"id": "next", "kind": NodeKind.DECISION.value, "status": "open", "question": "Q?"},
    ]
    doc["spec"]["edges"] = [{"from": "human", "to": "next"}]
    _write_graph(tmp_path, unit_id, doc)
    result = collect_decision_frontier_summary(tmp_path, unit_id)
    assert result["verdict"] == "pass"
    assert result["readyCount"] == 0
    assert result["blockedHumanActionCount"] == 1
    assert result["blockedHumanActions"][0]["nodeId"] == "human"


def test_journal_receipt_clears_blocked_human_action(tmp_path: Path) -> None:
    unit_id = "tasks-280-engineering-decision-layer"
    doc = minimal_fixture_graph()
    doc["spec"]["nodes"] = [
        {
            "id": "human",
            "kind": NodeKind.HUMAN_ACTION.value,
            "status": "open",
            "title": "Approve",
        },
    ]
    _write_graph(tmp_path, unit_id, doc)
    journal = DecisionRunJournal(tmp_path, "decision-run-1")
    receipt = build_receipt_envelope(
        node_id="human",
        actor="t@t.com",
        outcome="approved",
    ).as_dict()
    journal.append_human_action(
        "human-action:human",
        node_id="human",
        receipt=receipt,
        actor="t@t.com",
    )
    result = collect_decision_frontier_summary(tmp_path, unit_id, run_id="decision-run-1")
    assert result["blockedHumanActionCount"] == 0
