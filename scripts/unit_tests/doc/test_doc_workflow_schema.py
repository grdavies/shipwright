"""PRD 090 R4 — doc_workflow_schema generation and golden-diff."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from doc_workflow_schema import (
    build_schema,
    check_sw_doc_parity,
    lint_guideline_pack_stage_ids,
    render_stage_order_prose,
    render_stage_table,
    sync_sw_doc_markers,
    write_transitions_json,
)


def test_schema_matches_doc_loop_sequence() -> None:
    schema = build_schema()
    assert schema["stageSequence"][0] == "triage"
    assert schema["stageSequence"][-1] == "complete"
    assert "brainstorm" in schema["stageSequence"]


def test_regenerating_stage_table_is_idempotent(repo_root: Path) -> None:
    sync_sw_doc_markers(repo_root)
    ok, reasons = check_sw_doc_parity(repo_root)
    assert ok, reasons
    assert sync_sw_doc_markers(repo_root) is False


def test_transitions_json_matches_schema(repo_root: Path) -> None:
    write_transitions_json(repo_root)
    path = repo_root / "core/sw-reference/doc-workflow-transitions.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored == build_schema()


def test_sw_doc_markers_present(repo_root: Path) -> None:
    text = (repo_root / "core/commands/sw-doc.md").read_text(encoding="utf-8")
    assert render_stage_order_prose() in text
    assert render_stage_table() in text


def test_doc_pack_uses_driver_stage_ids(repo_root: Path) -> None:
    pack_path = repo_root / "core/sw-reference/guidelines/doc.pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    ok, reasons = lint_guideline_pack_stage_ids(pack)
    assert ok, reasons
    assert "sw-triage" not in pack.get("candidateSteps", [])


@pytest.mark.parametrize(
    "tier,after_triage",
    [
        ("Standard", "prd"),
        ("Full", "brainstorm"),
    ],
)
def test_transition_edges_for_tier(tier: str, after_triage: str) -> None:
    schema = build_schema()
    edges = schema["transitions"][tier]
    assert edges["triage"] == [after_triage]
