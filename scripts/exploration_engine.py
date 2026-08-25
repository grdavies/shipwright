#!/usr/bin/env python3
"""Destination-first structured exploration engine (PRD 331 R4, R5, R39)."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from exploration_policy import (
    DEFAULT_INTERACTION_MODE,
    GRAPH_INTERACTION_MODE,
    evaluate_promotion_trigger,
    interaction_mode_for,
)
from exploration_store import ExplorationStore, utc_now

REQUIRED_STRUCTURED_FIELDS: tuple[str, ...] = ("problem", "outcomes", "successCriteria")

OPTIONAL_STRUCTURED_FIELDS: tuple[str, ...] = (
    "constraints",
    "nonGoals",
    "assumptions",
    "knownFacts",
    "unknowns",
    "stakeholders",
    "evidenceNeeds",
    "candidateApproaches",
    "risks",
    "planningUnitCandidates",
)

STRING_FIELDS = frozenset({"problem"})
LIST_FIELDS = frozenset(
    {
        "outcomes",
        "successCriteria",
        "constraints",
        "nonGoals",
        "assumptions",
        "knownFacts",
        "stakeholders",
        "evidenceNeeds",
        "candidateApproaches",
        "risks",
    }
)


class ExplorationEngineError(RuntimeError):
    """Invalid exploration engine operation."""


class GraphExpansionRefusedError(ExplorationEngineError):
    """Graph nodes cannot be added before destination and promotion gates pass."""


class DestinationRequiredError(ExplorationEngineError):
    """Destination statement must be captured before downstream expansion."""


def _empty_triggers() -> dict[str, Any]:
    return {
        "blockingUnknowns": False,
        "resumeRequired": False,
        "promoteReceipt": None,
    }


def _destination_document(statement: str) -> dict[str, Any]:
    cleaned = statement.strip()
    if not cleaned:
        raise DestinationRequiredError("destination-statement-required")
    return {
        "statement": cleaned,
        "nonCommittal": True,
        "updatedAt": utc_now(),
    }


def destination_ready(map_document: Mapping[str, Any]) -> bool:
    destination = map_document.get("destination")
    if not isinstance(destination, dict):
        return False
    statement = str(destination.get("statement") or "").strip()
    return bool(statement) and destination.get("nonCommittal") is True


def structured_field_progress(map_document: Mapping[str, Any]) -> dict[str, Any]:
    structured = map_document.get("structuredFields")
    fields = structured if isinstance(structured, dict) else {}
    required_complete: list[str] = []
    required_missing: list[str] = []
    for name in REQUIRED_STRUCTURED_FIELDS:
        if _field_populated(name, fields.get(name)):
            required_complete.append(name)
        else:
            required_missing.append(name)
    optional_present = [
        name for name in OPTIONAL_STRUCTURED_FIELDS if name in fields and fields.get(name) not in (None, "", [])
    ]
    return {
        "requiredComplete": required_complete,
        "requiredMissing": required_missing,
        "optionalPresent": optional_present,
        "allRequiredComplete": not required_missing,
    }


def _field_populated(name: str, value: object) -> bool:
    if name in STRING_FIELDS:
        return isinstance(value, str) and bool(value.strip())
    if name in LIST_FIELDS:
        return isinstance(value, list) and bool(value)
    if name == "unknowns":
        return isinstance(value, list)
    if name == "planningUnitCandidates":
        return isinstance(value, list)
    return value not in (None, "", [])


def _normalize_structured_value(field: str, value: object) -> object:
    if field in STRING_FIELDS:
        if not isinstance(value, str) or not value.strip():
            raise ExplorationEngineError(f"invalid-structured-field:{field}")
        return value.strip()
    if field in LIST_FIELDS:
        if not isinstance(value, list) or not value:
            raise ExplorationEngineError(f"invalid-structured-field:{field}")
        normalized = [str(item).strip() for item in value if str(item).strip()]
        if not normalized:
            raise ExplorationEngineError(f"invalid-structured-field:{field}")
        return normalized
    if field == "unknowns":
        if not isinstance(value, list):
            raise ExplorationEngineError(f"invalid-structured-field:{field}")
        return deepcopy(value)
    if field == "planningUnitCandidates":
        if not isinstance(value, list):
            raise ExplorationEngineError(f"invalid-structured-field:{field}")
        return deepcopy(value)
    raise ExplorationEngineError(f"unknown-structured-field:{field}")


class ExplorationEngine:
    """Destination-first structured field collection with gated graph expansion."""

    def __init__(self, store: ExplorationStore) -> None:
        self._store = store
        self._session_modes: dict[str, str] = {}

    def session_state(self, map_id: str) -> dict[str, Any]:
        mode = interaction_mode_for(map_id, session_modes=self._session_modes)
        live = self._store.read(map_id)
        progress = structured_field_progress(live["map"]) if live else {"allRequiredComplete": False}
        return {
            "mapId": map_id,
            "interactionMode": mode,
            "destinationReady": destination_ready(live["map"]) if live else False,
            "structuredFieldProgress": progress,
        }

    def start_session(
        self,
        *,
        map_id: str,
        destination_statement: str,
        source: str = "conversation",
        notebook_id: str | None = None,
    ) -> dict[str, Any]:
        provenance: dict[str, Any] = {"createdAt": utc_now(), "source": source}
        if notebook_id:
            provenance["notebookId"] = notebook_id
        document = {
            "id": map_id,
            "version": "ExplorationMap@v1",
            "revision": 1,
            "destination": _destination_document(destination_statement),
            "structuredFields": {},
            "nodes": [],
            "persistenceTriggers": _empty_triggers(),
            "provenance": provenance,
        }
        created = self._store.create(document)
        self._session_modes[map_id] = DEFAULT_INTERACTION_MODE
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": created["map"],
            "interactionMode": DEFAULT_INTERACTION_MODE,
        }

    def set_destination(
        self,
        map_id: str,
        statement: str,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        updated = self._store.update(
            map_id,
            {"destination": _destination_document(statement)},
            expected_revision=expected_revision,
        )
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": updated["map"],
            "revision": updated["revision"],
        }

    def set_structured_field(
        self,
        map_id: str,
        field: str,
        value: object,
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        allowed = set(REQUIRED_STRUCTURED_FIELDS) | set(OPTIONAL_STRUCTURED_FIELDS)
        if field not in allowed:
            raise ExplorationEngineError(f"unknown-structured-field:{field}")
        live = self._store.read(map_id)
        if live is None:
            raise ExplorationEngineError("map-not-found")
        if not destination_ready(live["map"]):
            raise DestinationRequiredError("destination-required-before-structured-fields")
        structured = deepcopy(live["map"].get("structuredFields") or {})
        structured[field] = _normalize_structured_value(field, value)
        updated = self._store.update(
            map_id,
            {"structuredFields": structured},
            expected_revision=expected_revision,
        )
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": updated["map"],
            "revision": updated["revision"],
            "structuredFieldProgress": structured_field_progress(updated["map"]),
        }

    def promote_to_graph(
        self,
        map_id: str,
        *,
        trigger: str,
        expected_revision: int,
        context: Mapping[str, Any] | None = None,
        promote_receipt: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        live = self._store.read(map_id)
        if live is None:
            raise ExplorationEngineError("map-not-found")
        decision = evaluate_promotion_trigger(
            live["map"],
            trigger=trigger,
            session_modes=self._session_modes,
            context=context,
        )
        if decision.get("verdict") != "allow":
            return {"verdict": "refused", **decision}
        patch: dict[str, Any] = {}
        if promote_receipt is not None:
            triggers = deepcopy(live["map"].get("persistenceTriggers") or _empty_triggers())
            triggers["promoteReceipt"] = deepcopy(dict(promote_receipt))
            patch["persistenceTriggers"] = triggers
        updated = self._store.update(map_id, patch, expected_revision=expected_revision)
        self._session_modes[map_id] = GRAPH_INTERACTION_MODE
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": updated["map"],
            "revision": updated["revision"],
            "interactionMode": GRAPH_INTERACTION_MODE,
            "trigger": trigger,
        }

    def add_graph_node(
        self,
        map_id: str,
        node: Mapping[str, Any],
        *,
        expected_revision: int,
    ) -> dict[str, Any]:
        live = self._store.read(map_id)
        if live is None:
            raise ExplorationEngineError("map-not-found")
        if not destination_ready(live["map"]):
            raise GraphExpansionRefusedError("destination-required-before-graph-expansion")
        mode = interaction_mode_for(map_id, session_modes=self._session_modes)
        if mode != GRAPH_INTERACTION_MODE:
            raise GraphExpansionRefusedError("graph-promotion-required-before-expansion")
        node_copy = deepcopy(dict(node))
        node_id = str(node_copy.get("id") or "").strip()
        node_type = str(node_copy.get("type") or "").strip()
        status = str(node_copy.get("status") or "open")
        if not node_id or not node_type:
            raise ExplorationEngineError("invalid-graph-node")
        node_copy.setdefault("status", status)
        nodes = [deepcopy(item) for item in live["map"].get("nodes") or [] if isinstance(item, dict)]
        nodes.append(node_copy)
        updated = self._store.update(map_id, {"nodes": nodes}, expected_revision=expected_revision)
        return {
            "verdict": "ok",
            "mapId": map_id,
            "map": updated["map"],
            "revision": updated["revision"],
            "nodeId": node_id,
        }
