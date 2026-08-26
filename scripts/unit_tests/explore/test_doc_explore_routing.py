"""PRD 331 R26, R27, R31, R50 — explore↔doc bidirectional handoff routing."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_brief import emit_brief, invalidate_brief  # noqa: E402
from planning_readiness import compute_readiness  # noqa: E402
from workflow_extensions import (  # noqa: E402
    apply_doc_backward_cancel,
    apply_doc_backward_confirm,
    apply_explore_forward_confirm,
    apply_explore_forward_decline,
    propose_doc_backward_route,
    propose_explore_forward_handoff,
    recover_from_loop_guard,
    refuse_handoff_dispatch,
    validate_doc_explore_handoff_contract,
)


def _map(*, map_id: str = "map-handoff", revision: int = 1, blocking: bool = True) -> dict:
    unknowns = (
        [
            {
                "id": "unk-blocking",
                "statement": "Which doc tier applies?",
                "classification": "blocking",
            }
        ]
        if blocking
        else []
    )
    return {
        "id": map_id,
        "version": "ExplorationMap@v1",
        "revision": revision,
        "destination": {"statement": "Ship explore↔doc bidirectional handoff"},
        "structuredFields": {
            "problem": "Premature doc routing must fail closed.",
            "outcomes": ["Explicit handoffs only"],
            "successCriteria": ["Loop guard enforced"],
            "unknowns": unknowns,
            "planningUnitCandidates": [
                {
                    "id": "unit-a",
                    "title": "Doc backward route",
                    "rationale": "Insufficient readiness returns to explore.",
                },
                {
                    "id": "unit-b",
                    "title": "Explore forward route",
                    "rationale": "Ready brief forwards to doc.",
                    "dependencies": ["unit-a"],
                },
            ],
        },
        "nodes": [],
        "provenance": {"createdAt": "2026-08-25T00:00:00Z", "source": "conversation"},
    }


def test_doc_routes_backward_when_not_ready() -> None:
    """R26 traceability: insufficient readiness proposes cancelable backward route."""
    # Z — no readiness supplied; recompute from map
    proposal = propose_doc_backward_route(_map(blocking=True), readiness=None)
    assert proposal["verdict"] == "propose"
    assert proposal["direction"] == "backward"
    assert proposal["destination"] == "explore"
    assert "resume map-handoff" in proposal["command"]
    assert proposal["reason"]["code"] == "doc-readiness-insufficient"
    assert proposal["readOnlyUntilConfirm"] is True
    assert proposal["persistenceEffects"]
    assert proposal["loopGuardToken"]

    # O — one blocking unknown cited
    readiness = compute_readiness(_map(blocking=True))
    one_blocker = propose_doc_backward_route(_map(blocking=True), readiness=readiness)
    assert one_blocker["reason"]["evidence"]["blockingCount"] == 1

    # M — many blockers via open questions
    many_map = _map(blocking=False)
    many_map["nodes"] = [
        {"id": "q1", "type": "question", "status": "open", "statement": "A?"},
        {"id": "q2", "type": "question", "status": "open", "statement": "B?"},
    ]
    many_map["structuredFields"]["unknowns"] = [
        {"id": "b1", "statement": "Block 1", "classification": "blocking"},
        {"id": "b2", "statement": "Block 2", "classification": "blocking"},
    ]
    many = propose_doc_backward_route(many_map)
    assert many["verdict"] == "propose"
    assert many["reason"]["evidence"]["blockingCount"] >= 2

    # B — readiness edge: sufficient readiness refuses backward
    ready_map = _map(blocking=False)
    ready = compute_readiness(ready_map)
    edge = propose_doc_backward_route(ready_map, readiness=ready)
    assert edge["verdict"] == "refused"
    assert edge["reason"] == "doc-readiness-sufficient"

    # I — handoff reason present
    assert proposal["reason"]["message"]

    # E — canceled route clears persistence
    cancelled = apply_doc_backward_cancel(proposal)
    assert cancelled["verdict"] == "cancelled"
    assert cancelled["persistenceEffects"] == []

    # S — loop token recorded on proposal
    assert proposal["loopGuardToken"][-1] == "explore"


def test_ready_explore_routes_forward_explicitly() -> None:
    """R27 traceability: ready exploration proposes explicit forward doc handoff."""
    ready_map = _map(blocking=False)

    # Z — no brief supplied; derive from map
    proposal = propose_explore_forward_handoff(ready_map)
    assert proposal["verdict"] == "propose"
    assert proposal["direction"] == "forward"
    assert proposal["destination"] == "doc"
    assert proposal["command"] == "/sw-doc --from-explore map-handoff"
    assert proposal["implements"] is False
    assert proposal["readOnlyUntilConfirm"] is True
    assert proposal["loopGuardToken"]

    # O — ready brief attached
    brief = emit_brief(ready_map)
    with_brief = propose_explore_forward_handoff(ready_map, brief=brief)
    assert with_brief["briefId"] == brief["id"]

    # M — many candidates surface on proposal
    assert len(with_brief["planningUnitCandidates"]) >= 2

    # B — stale brief refused
    stale_brief = invalidate_brief(brief, current_revision=2)
    stale = propose_explore_forward_handoff(ready_map, brief=stale_brief)
    assert stale["verdict"] == "refused"
    assert stale["reason"] == "stale-brief-or-readiness"

    # I — doc handoff command declared
    assert with_brief["reason"]["code"] == "exploration-ready-for-doc"

    # E — declined confirm
    declined = apply_explore_forward_decline(with_brief)
    assert declined["verdict"] == "declined"
    assert declined["persistenceEffects"] == []

    # S — completed handoff confirm never implements
    confirmed = apply_explore_forward_confirm(with_brief, operator="operator-1")
    assert confirmed["verdict"] == "confirmed"
    assert confirmed["implements"] is False
    assert confirmed["command"].startswith("/sw-doc --from-explore")


def test_explore_cannot_dispatch_implementation() -> None:
    """R31 — forward/backward confirm refuses implementation dispatch."""
    ready_map = _map(blocking=False)
    proposal = propose_explore_forward_handoff(ready_map)
    refused = apply_explore_forward_confirm(
        proposal,
        operator="operator-1",
        dispatch_command="/sw-deliver run tasks.md",
    )
    assert refused["verdict"] == "refused"
    assert refused["reason"] in {
        "implementation-dispatch-forbidden",
        "nested-orchestrator-dispatch-forbidden",
    }

    backward = propose_doc_backward_route(_map(blocking=True))
    refused_backward = apply_doc_backward_confirm(
        backward,
        operator="operator-1",
        dispatch_command="/sw-execute",
    )
    assert refused_backward["verdict"] == "refused"
    assert refused_backward["reason"] == "implementation-dispatch-forbidden"


def test_nested_orchestrator_dispatch_refused() -> None:
    """Nested /sw-doc or /sw-deliver injection during handoff is refused (R26, R50)."""
    nested_doc = refuse_handoff_dispatch("/sw-deliver run tasks.md")
    assert nested_doc["verdict"] == "refused"

    nested_deliver = refuse_handoff_dispatch("/sw-doc --topic x")
    assert nested_deliver["verdict"] == "refused"
    assert nested_deliver["reason"] == "nested-orchestrator-dispatch-forbidden"

    allowed_explore = refuse_handoff_dispatch(
        "/sw-explore resume map-1",
        allowed_commands=frozenset({"/sw-explore"}),
    )
    assert allowed_explore["verdict"] == "allow"


def test_loop_guard_blocks_and_recovers() -> None:
    """R50 — bounded explore↔doc alternation and explicit loop recovery."""
    history = ["explore", "doc", "explore", "doc"]
    blocked = propose_doc_backward_route(_map(blocking=True), route_history=history)
    assert blocked["verdict"] == "refused"
    assert blocked["reason"] == "explore-doc-loop-guard"

    recovery = recover_from_loop_guard(
        route_history=history,
        break_destination="deliver",
        operator="operator-1",
    )
    assert recovery["verdict"] == "recovered"
    assert recovery["destination"] == "deliver"
    assert recovery["persistenceEffects"]

    invalid = recover_from_loop_guard(
        route_history=history,
        break_destination="doc",
        operator="operator-1",
    )
    assert invalid["verdict"] == "refused"


def test_doc_explore_handoff_contract_documented() -> None:
    result = validate_doc_explore_handoff_contract()
    assert result["verdict"] == "pass", result.get("failures")
    assert all(result["controls"].values())


def test_backward_confirm_dispatches_explore_only() -> None:
    proposal = propose_doc_backward_route(_map(blocking=True))
    confirmed = apply_doc_backward_confirm(proposal, operator="operator-1")
    assert confirmed["verdict"] == "confirmed"
    assert confirmed["command"].startswith("/sw-explore resume")
