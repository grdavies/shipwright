#!/usr/bin/env python3
"""WorkflowGraph human-action node kind and backend tests (PRD 280 R13)."""
from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_backend import (  # noqa: E402
    HostExecutionHints,
    HumanActionExecutionBackend,
    SubmitRequest,
)
from graph.node_kinds import (  # noqa: E402
    CLOSED_NODE_KINDS,
    HUMAN_ACTION_KIND,
    is_human_action_kind,
    node_awaits_human,
)


def test_human_action_kind_registered() -> None:
    assert is_human_action_kind(HUMAN_ACTION_KIND)
    assert HUMAN_ACTION_KIND in CLOSED_NODE_KINDS


def test_human_action_node_awaits_human() -> None:
    node = {"id": "ha1", "kind": HUMAN_ACTION_KIND, "title": "Approve"}
    assert node_awaits_human(node) is True


def test_backend_surfaces_await_human_without_receipt() -> None:
    backend = HumanActionExecutionBackend()
    request = SubmitRequest(
        idempotency_key="ha-1",
        node={
            "id": "ha1",
            "kind": HUMAN_ACTION_KIND,
            "title": "Approve deploy",
        },
        capability_token="",
        input_hashes=(),
        host_hints=HostExecutionHints(mutating=False, purity="read-only"),
    )
    submit = backend.submit(request)
    terminal = backend.result(submit.handle)
    assert terminal.report.coverage.get("awaitHuman") is True
    assert terminal.report.retry_only is True


def test_backend_consumes_verified_receipt() -> None:
    from decision_graph.receipt import build_receipt_envelope

    backend = HumanActionExecutionBackend()
    request = SubmitRequest(
        idempotency_key="ha-2",
        node={"id": "ha1", "kind": HUMAN_ACTION_KIND, "title": "Approve deploy"},
        capability_token="",
        input_hashes=(),
        host_hints=HostExecutionHints(mutating=False, purity="read-only"),
    )
    submit = backend.submit(request)
    receipt = build_receipt_envelope(
        node_id="ha1",
        actor="operator@example.com",
        outcome="approved",
    ).as_dict()
    terminal = backend.consume_receipt(submit.handle, receipt)
    assert terminal.report.verdict == "pass"
    assert terminal.report.coverage.get("receiptConsumed") is True
