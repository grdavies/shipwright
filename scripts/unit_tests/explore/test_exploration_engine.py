"""PRD 331 D1, R4, R5, R6, R7 — destination-first structured exploration engine."""

from __future__ import annotations

from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from exploration_engine import (  # noqa: E402
    ExplorationEngine,
    GraphExpansionRefusedError,
    REQUIRED_STRUCTURED_FIELDS,
    structured_field_progress,
)
from exploration_policy import (  # noqa: E402
    TierRoutingForbiddenError,
    entry_tier_routing_forbidden,
    evaluate_promotion_trigger,
    resolve_entry_tier,
)
from exploration_store import ExplorationStore  # noqa: E402


def test_destination_precedes_graph_expansion(tmp_path: Path) -> None:
    engine = ExplorationEngine(ExplorationStore(tmp_path))
    started = engine.start_session(
        map_id="explore-destination-first",
        destination_statement="Understand whether destination-first exploration improves planning readiness.",
    )
    with pytest.raises(GraphExpansionRefusedError, match="graph-promotion-required"):
        engine.add_graph_node(
            "explore-destination-first",
            {"id": "q-1", "type": "question", "status": "open", "statement": "What is unknown?"},
            expected_revision=started["map"]["revision"],
        )


def test_structured_fields_round_trip(tmp_path: Path) -> None:
    engine = ExplorationEngine(ExplorationStore(tmp_path))
    started = engine.start_session(
        map_id="explore-fields",
        destination_statement="Capture structured fields without forcing planning.",
    )
    revision = started["map"]["revision"]
    progress = structured_field_progress(started["map"])
    assert progress["requiredMissing"] == list(REQUIRED_STRUCTURED_FIELDS)

    updated = engine.set_structured_field(
        "explore-fields",
        "problem",
        "Operators need clearer exploration before doc work.",
        expected_revision=revision,
    )
    revision = updated["revision"]
    assert updated["structuredFieldProgress"]["requiredComplete"] == ["problem"]

    for field, value in (
        ("outcomes", ["Reduce premature doc routing"]),
        ("successCriteria", ["Operators can resume exploration with structured context"]),
        ("constraints", ["No implementation dispatch from explore"]),
        ("nonGoals", ["Auto-create PRDs"]),
    ):
        result = engine.set_structured_field(
            "explore-fields",
            field,
            value,
            expected_revision=revision,
        )
        revision = result["revision"]

    final = engine._store.read("explore-fields")
    assert final is not None
    structured = final["map"]["structuredFields"]
    assert structured["problem"].startswith("Operators need")
    assert structured["constraints"] == ["No implementation dispatch from explore"]
    assert structured_field_progress(final["map"])["allRequiredComplete"] is True


def test_conversation_promotes_only_when_warranted(tmp_path: Path) -> None:
    engine = ExplorationEngine(ExplorationStore(tmp_path))
    started = engine.start_session(
        map_id="explore-promote",
        destination_statement="Promote only when triggers are satisfied.",
    )
    revision = started["map"]["revision"]
    denied = engine.promote_to_graph(
        "explore-promote",
        trigger="undefined-trigger",
        expected_revision=revision,
    )
    assert denied["verdict"] == "refused"
    assert denied["reason"] == "undefined-trigger"

    denied_operator = engine.promote_to_graph(
        "explore-promote",
        trigger="operator_explicit_promote",
        expected_revision=revision,
    )
    assert denied_operator["verdict"] == "refused"
    assert denied_operator["reason"] == "operator-confirmation-required"

    allowed = engine.promote_to_graph(
        "explore-promote",
        trigger="operator_explicit_promote",
        expected_revision=revision,
        context={"operatorConfirmed": True},
        promote_receipt={"receiptId": "rcpt-1", "issuedAt": "2026-08-25T00:00:00Z"},
    )
    assert allowed["verdict"] == "ok"
    assert allowed["interactionMode"] == "graph"
    persisted = engine._store.persist("explore-promote", expected_revision=allowed["revision"])
    assert persisted["persisted"] is True


def test_explore_entry_never_resolves_qsf_tier() -> None:
    contract = entry_tier_routing_forbidden()
    assert contract["verdict"] == "forbidden"
    assert contract["resolvedTier"] is None
    assert "quick" in contract["tiers"]
    with pytest.raises(TierRoutingForbiddenError):
        resolve_entry_tier(input_text="quick standard full tier routing")


def test_stance_b_conversation_first_promotion(tmp_path: Path) -> None:
    engine = ExplorationEngine(ExplorationStore(tmp_path))
    started = engine.start_session(
        map_id="explore-stance-b",
        destination_statement="Conversation remains default until promotion.",
    )
    assert engine.session_state("explore-stance-b")["interactionMode"] == "conversation"

    revision = started["map"]["revision"]
    for field, value in (
        ("problem", "Need a conversation-first exploration stance."),
        ("outcomes", ["Conversation before graph"]),
        ("successCriteria", ["Promotion only on trigger"]),
    ):
        result = engine.set_structured_field(
            "explore-stance-b",
            field,
            value,
            expected_revision=revision,
        )
        revision = result["revision"]

    live = engine._store.read("explore-stance-b")
    assert live is not None
    decision = evaluate_promotion_trigger(
        live["map"],
        trigger="structured_fields_complete",
        session_modes=engine._session_modes,
    )
    assert decision["verdict"] == "allow"

    promoted = engine.promote_to_graph(
        "explore-stance-b",
        trigger="structured_fields_complete",
        expected_revision=revision,
    )
    assert promoted["interactionMode"] == "graph"
    node = engine.add_graph_node(
        "explore-stance-b",
        {"id": "disc-1", "type": "discovery", "status": "open", "statement": "Promotion unlocked graph."},
        expected_revision=promoted["revision"],
    )
    assert node["verdict"] == "ok"
