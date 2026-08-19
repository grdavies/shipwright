#!/usr/bin/env python3
"""Human-action procedure and receipt unit tests (PRD 280 R11/R12/R14)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.human_action import (  # noqa: E402
    parse_human_action_node,
    render_procedure_markdown,
)
from decision_graph.receipt import (  # noqa: E402
    admission_allowed,
    build_receipt_envelope,
    compute_content_hash,
    validate_receipt,
)


def test_render_procedure_from_title_only() -> None:
    node = {
        "id": "approve",
        "kind": "human-action",
        "status": "open",
        "title": "Approve deploy",
    }
    markdown = render_procedure_markdown(node)
    assert "# Human action: Approve deploy" in markdown
    assert "1. Complete: Approve deploy" in markdown


def test_render_procedure_with_steps_and_artifacts() -> None:
    node = {
        "id": "signoff",
        "kind": "human-action",
        "status": "open",
        "title": "Security sign-off",
        "procedure": {
            "steps": ["Review threat model", "Acknowledge residual risk"],
            "artifacts": ["threat-model.pdf"],
        },
    }
    procedure = parse_human_action_node(node)
    assert procedure.steps == ("Review threat model", "Acknowledge residual risk")
    assert procedure.artifacts == ("threat-model.pdf",)


def test_valid_receipt_passes_hash_and_actor() -> None:
    envelope = build_receipt_envelope(
        node_id="approve",
        actor="t@t.com",
        outcome="approved",
    )
    result = validate_receipt(envelope.as_dict(), expected_node_id="approve")
    assert result["verdict"] == "pass"


def test_tampered_receipt_fails_closed() -> None:
    envelope = build_receipt_envelope(
        node_id="approve",
        actor="t@t.com",
        outcome="approved",
    )
    document = envelope.as_dict()
    document["contentHash"] = "0" * 64
    result = validate_receipt(document, expected_node_id="approve")
    assert result["verdict"] == "fail"
    assert result["code"] == "receipt:hash-mismatch"


def test_missing_receipt_blocks_dependent_admission() -> None:
    graph = {
        "spec": {
            "nodes": [
                {
                    "id": "human",
                    "kind": "human-action",
                    "status": "open",
                    "title": "Approve",
                },
                {"id": "next", "kind": "decision", "status": "open", "question": "Q?"},
            ],
            "edges": [{"from": "human", "to": "next"}],
        }
    }
    blocked = admission_allowed(graph, "next", {})
    assert blocked["verdict"] == "fail"
    assert blocked["code"] == "frontier:blocked-by-receipt"


def test_verified_receipt_unblocks_admission() -> None:
    graph = {
        "spec": {
            "nodes": [
                {
                    "id": "human",
                    "kind": "human-action",
                    "status": "open",
                    "title": "Approve",
                },
                {"id": "next", "kind": "decision", "status": "open", "question": "Q?"},
            ],
            "edges": [{"from": "human", "to": "next"}],
        }
    }
    receipt = build_receipt_envelope(
        node_id="human",
        actor="t@t.com",
        outcome="approved",
    ).as_dict()
    allowed = admission_allowed(graph, "next", {"human": receipt})
    assert allowed["verdict"] == "pass"


def test_compute_content_hash_is_stable() -> None:
    first = compute_content_hash({"nodeId": "n1", "outcome": "ok", "rationale": ""})
    second = compute_content_hash({"nodeId": "n1", "outcome": "ok", "rationale": ""})
    assert first == second
