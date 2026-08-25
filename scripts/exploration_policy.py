#!/usr/bin/env python3
"""Conversational promotion and no-tier entry policy (PRD 331 R6, R7, R37)."""
from __future__ import annotations

from typing import Any, Mapping

DEFAULT_INTERACTION_MODE = "conversation"
GRAPH_INTERACTION_MODE = "graph"

# Graph promotion is allowed only for these named triggers (R6, D1).
PROMOTION_TRIGGERS: frozenset[str] = frozenset(
    {
        "blocking_unknown_resolved",
        "operator_explicit_promote",
        "evidence_sufficient",
        "structured_fields_complete",
    }
)

# Quick / Standard / Full tier routing is absent at explore entry (R7).
FORBIDDEN_ENTRY_TIERS: frozenset[str] = frozenset({"quick", "standard", "full"})


class ExplorationPolicyError(ValueError):
    """Invalid exploration policy transition."""


class TierRoutingForbiddenError(ExplorationPolicyError):
    """Explore entry must not resolve QSF tier classification (R7)."""


def entry_tier_routing_forbidden() -> dict[str, Any]:
    """Return the canonical no-tier-at-entry contract (R7)."""
    return {
        "verdict": "forbidden",
        "reason": "no-tier-at-explore-entry",
        "tiers": sorted(FORBIDDEN_ENTRY_TIERS),
        "resolvedTier": None,
    }


def resolve_entry_tier(**_kwargs: object) -> dict[str, Any]:
    """Fail closed — tier routing is never invoked at explore entry (R7)."""
    raise TierRoutingForbiddenError("tier-routing-forbidden-at-explore-entry")


def interaction_mode_for(map_id: str, *, session_modes: Mapping[str, str]) -> str:
    """Conversation remains the default until graph promotion (R6)."""
    mode = session_modes.get(map_id, DEFAULT_INTERACTION_MODE)
    if mode == GRAPH_INTERACTION_MODE:
        return GRAPH_INTERACTION_MODE
    return DEFAULT_INTERACTION_MODE


def _structured_fields_complete(map_document: Mapping[str, Any]) -> bool:
    structured = map_document.get("structuredFields")
    if not isinstance(structured, dict):
        return False
    for field in ("problem", "outcomes", "successCriteria"):
        value = structured.get(field)
        if field == "problem":
            if not isinstance(value, str) or not value.strip():
                return False
            continue
        if not isinstance(value, list) or not value:
            return False
    return True


def _blocking_unknowns_resolved(map_document: Mapping[str, Any]) -> bool:
    structured = map_document.get("structuredFields")
    if not isinstance(structured, dict):
        return False
    unknowns = structured.get("unknowns")
    if not isinstance(unknowns, list):
        return True
    for item in unknowns:
        if isinstance(item, dict) and item.get("classification") == "blocking":
            return False
    return True


def evaluate_promotion_trigger(
    map_document: Mapping[str, Any],
    *,
    trigger: str,
    session_modes: Mapping[str, str],
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Graph promotion follows only defined triggers; conversation stays default (R6)."""
    map_id = str(map_document.get("id") or "")
    mode = interaction_mode_for(map_id, session_modes=session_modes)
    if mode == GRAPH_INTERACTION_MODE:
        return {"verdict": "refused", "reason": "already-promoted", "trigger": trigger}
    if trigger not in PROMOTION_TRIGGERS:
        return {"verdict": "refused", "reason": "undefined-trigger", "trigger": trigger}

    ctx = dict(context or {})
    if trigger == "operator_explicit_promote":
        if ctx.get("operatorConfirmed") is not True:
            return {"verdict": "refused", "reason": "operator-confirmation-required", "trigger": trigger}
        return {"verdict": "allow", "trigger": trigger, "mode": GRAPH_INTERACTION_MODE}
    if trigger == "structured_fields_complete":
        if not _structured_fields_complete(map_document):
            return {"verdict": "refused", "reason": "structured-fields-incomplete", "trigger": trigger}
        return {"verdict": "allow", "trigger": trigger, "mode": GRAPH_INTERACTION_MODE}
    if trigger == "blocking_unknown_resolved":
        if not _blocking_unknowns_resolved(map_document):
            return {"verdict": "refused", "reason": "blocking-unknowns-remain", "trigger": trigger}
        return {"verdict": "allow", "trigger": trigger, "mode": GRAPH_INTERACTION_MODE}
    if trigger == "evidence_sufficient":
        nodes = map_document.get("nodes")
        evidence_nodes = [
            node
            for node in (nodes if isinstance(nodes, list) else [])
            if isinstance(node, dict) and node.get("type") == "evidence"
        ]
        if not evidence_nodes:
            return {"verdict": "refused", "reason": "evidence-insufficient", "trigger": trigger}
        return {"verdict": "allow", "trigger": trigger, "mode": GRAPH_INTERACTION_MODE}

    return {"verdict": "refused", "reason": "trigger-conditions-unmet", "trigger": trigger}
