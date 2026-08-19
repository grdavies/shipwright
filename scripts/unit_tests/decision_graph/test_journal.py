#!/usr/bin/env python3
"""Decision run journal unit tests (PRD 280 R19)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.journal import (  # noqa: E402
    DecisionJournalError,
    DecisionRunJournal,
    receipts_by_node_from_journal,
)
from decision_graph.receipt import build_receipt_envelope  # noqa: E402


def test_empty_journal_lists_no_events(tmp_path: Path) -> None:
    journal = DecisionRunJournal(tmp_path, "run-1")
    assert journal.list_events() == []
    assert journal.replay_events() == []


def test_append_resolution_is_idempotent(tmp_path: Path) -> None:
    journal = DecisionRunJournal(tmp_path, "run-1")
    first = journal.append_resolution(
        "resolution:d1",
        node_id="d1",
        outcome="approved",
        rationale="looks good",
    )
    second = journal.append_resolution(
        "resolution:d1",
        node_id="d1",
        outcome="approved",
        rationale="looks good",
    )
    assert first == second
    assert len(journal.list_events()) == 1
    assert len(journal.replay_events()) == 1


def test_conflicting_replay_fails_closed(tmp_path: Path) -> None:
    journal = DecisionRunJournal(tmp_path, "run-1")
    journal.append_resolution("resolution:d1", node_id="d1", outcome="approved")
    with pytest.raises(DecisionJournalError):
        journal.append_resolution("resolution:d1", node_id="d1", outcome="rejected")


def test_human_action_event_and_receipt_map(tmp_path: Path) -> None:
    journal = DecisionRunJournal(tmp_path, "run-1")
    receipt = build_receipt_envelope(
        node_id="approve",
        actor="t@t.com",
        outcome="approved",
    ).as_dict()
    journal.append_human_action(
        "human-action:approve",
        node_id="approve",
        receipt=receipt,
        actor="t@t.com",
    )
    events = journal.replay_events()
    assert len(events) == 1
    assert events[0]["eventType"] == "human-action"
    receipts = receipts_by_node_from_journal(journal)
    assert receipts["approve"]["nodeId"] == "approve"


def test_replay_matches_jsonl_order(tmp_path: Path) -> None:
    journal = DecisionRunJournal(tmp_path, "run-1")
    journal.append_resolution("resolution:a", node_id="a", outcome="one")
    journal.append_resolution("resolution:b", node_id="b", outcome="two")
    replayed = journal.replay_events()
    assert [event["nodeId"] for event in replayed] == ["a", "b"]
    jsonl = (tmp_path / ".cursor" / "sw-decision-runs" / "run-1" / "events.jsonl").read_text(
        encoding="utf-8"
    )
    assert jsonl.count("\n") == 2


def test_corrupt_event_file_raises(tmp_path: Path) -> None:
    journal = DecisionRunJournal(tmp_path, "run-1")
    journal.append_resolution("resolution:a", node_id="a", outcome="one")
    event_file = next((journal.run_dir / "events").glob("*.json"))
    event_file.write_text("{not-json", encoding="utf-8")
    with pytest.raises(DecisionJournalError):
        journal.list_events()
