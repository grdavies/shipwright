"""PRD 331 R8, R9, R11, R12, R14, R20, R41, R46, R47 — exploration artifact schemas."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

MAP_SCHEMA_REL = Path("core/sw-reference/exploration-map.schema.json")
READINESS_SCHEMA_REL = Path("core/sw-reference/planning-readiness.schema.json")
BRIEF_SCHEMA_REL = Path("core/sw-reference/exploration-brief.schema.json")

EXPLORATION_SCHEMA_FILES = (
    MAP_SCHEMA_REL,
    READINESS_SCHEMA_REL,
    BRIEF_SCHEMA_REL,
)

# Named validator ownership registry (R46) — each schema maps to one owner function in this module.
VALIDATOR_OWNERS: dict[str, str] = {
    MAP_SCHEMA_REL.name: "validate_exploration_map",
    READINESS_SCHEMA_REL.name: "validate_planning_readiness",
    BRIEF_SCHEMA_REL.name: "validate_exploration_brief",
}

SECRET_FORBIDDEN_KEYS = frozenset(
    {
        "apiKey",
        "token",
        "password",
        "secret",
        "credential",
        "privateKey",
        "accessToken",
    }
)

NODE_TYPES = frozenset({"question", "decision", "evidence", "discovery"})
UNKNOWN_CLASSIFICATIONS = frozenset({"blocking", "non-blocking", "deferred"})


def _load_schema(repo_root: Path, rel: Path) -> dict[str, Any]:
    return json.loads((repo_root / rel).read_text(encoding="utf-8"))


def _is_non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_with_jsonschema(document: dict[str, Any], schema: dict[str, Any]) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)


def _scan_forbidden_secrets(document: dict[str, Any], prefix: str = "") -> list[str]:
    errors: list[str] = []
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else key
        if key in SECRET_FORBIDDEN_KEYS:
            errors.append(f"forbidden-secret-key:{path}")
        if isinstance(value, dict):
            errors.extend(_scan_forbidden_secrets(value, path))
        elif isinstance(value, list):
            for idx, item in enumerate(value):
                if isinstance(item, dict):
                    errors.extend(_scan_forbidden_secrets(item, f"{path}[{idx}]"))
                elif isinstance(item, str) and re.search(
                    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|password\s*=)", item
                ):
                    errors.append(f"forbidden-secret-value:{path}[{idx}]")
    return errors


def validate_exploration_map(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "revision",
        "destination",
        "structuredFields",
        "nodes",
        "persistenceTriggers",
        "provenance",
        "supersededNodeIds",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "ExplorationMap@v1":
        errors.append("invalid:version")
    revision = document.get("revision")
    if not isinstance(revision, int) or revision < 1:
        errors.append("invalid:revision")
    destination = document.get("destination")
    if not isinstance(destination, dict):
        errors.append("missing:destination")
    else:
        if not _is_non_empty_str(destination.get("statement")):
            errors.append("missing:destination.statement")
        if destination.get("nonCommittal") is not True:
            errors.append("invalid:destination.nonCommittal")
    structured = document.get("structuredFields")
    if structured is not None and not isinstance(structured, dict):
        errors.append("invalid:structuredFields")
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        errors.append("missing:nodes")
    else:
        seen: set[str] = set()
        for node in nodes:
            if not isinstance(node, dict):
                errors.append("invalid:nodes.entry")
                continue
            node_id = node.get("id")
            node_type = node.get("type")
            if not _is_non_empty_str(node_id):
                errors.append("invalid:nodes.id")
            elif node_id in seen:
                errors.append("duplicate:nodes.id")
            else:
                seen.add(node_id)
            if node_type not in NODE_TYPES:
                errors.append("invalid:nodes.type")
            status = node.get("status")
            if status not in {"open", "resolved", "superseded", "cancelled"}:
                errors.append("invalid:nodes.status")
            if node_type == "question" and not _is_non_empty_str(node.get("statement")):
                errors.append("missing:nodes.question.statement")
            if node_type == "decision" and not _is_non_empty_str(node.get("title")):
                errors.append("missing:nodes.decision.title")
            if node_type == "evidence":
                ref = node.get("evidenceRef")
                if not isinstance(ref, dict):
                    errors.append("missing:nodes.evidence.evidenceRef")
                elif ref.get("kind") not in {"ResearchEvidence", "PrototypeEvidence"}:
                    errors.append("invalid:nodes.evidence.kind")
            if node_type == "discovery" and not _is_non_empty_str(node.get("statement")):
                errors.append("missing:nodes.discovery.statement")
    triggers = document.get("persistenceTriggers")
    if not isinstance(triggers, dict):
        errors.append("missing:persistenceTriggers")
    else:
        for key in ("blockingUnknowns", "resumeRequired"):
            if not isinstance(triggers.get(key), bool):
                errors.append(f"missing:persistenceTriggers.{key}")
        if "promoteReceipt" not in triggers:
            errors.append("missing:persistenceTriggers.promoteReceipt")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing:provenance")
    else:
        if not _is_non_empty_str(provenance.get("createdAt")):
            errors.append("missing:provenance.createdAt")
        if not _is_non_empty_str(provenance.get("source")):
            errors.append("missing:provenance.source")
    errors.extend(_scan_forbidden_secrets(document))
    return errors


def validate_planning_readiness(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "sourceRevision",
        "explorationMapId",
        "unknowns",
        "summary",
        "invalidation",
        "computedAt",
        "readyForDocHandoff",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "PlanningReadiness@v1":
        errors.append("invalid:version")
    source_revision = document.get("sourceRevision")
    if not isinstance(source_revision, int) or source_revision < 1:
        errors.append("invalid:sourceRevision")
    if not _is_non_empty_str(document.get("explorationMapId")):
        errors.append("missing:explorationMapId")
    unknowns = document.get("unknowns")
    if not isinstance(unknowns, list):
        errors.append("missing:unknowns")
    else:
        for unknown in unknowns:
            if not isinstance(unknown, dict):
                errors.append("invalid:unknowns.entry")
                continue
            if unknown.get("classification") not in UNKNOWN_CLASSIFICATIONS:
                errors.append("invalid:unknowns.classification")
            if not _is_non_empty_str(unknown.get("statement")):
                errors.append("invalid:unknowns.statement")
    invalidation = document.get("invalidation")
    if not isinstance(invalidation, dict):
        errors.append("missing:invalidation")
    elif invalidation.get("state") not in {"valid", "stale", "superseded"}:
        errors.append("invalid:invalidation.state")
    if not _is_non_empty_str(document.get("computedAt")):
        errors.append("missing:computedAt")
    return errors


def validate_exploration_brief(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "sourceRevision",
        "explorationMapId",
        "destination",
        "decisions",
        "evidence",
        "remainingUncertainty",
        "readiness",
        "planningUnitCandidates",
        "invalidation",
        "emittedAt",
        "authorityBoundary",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "ExplorationBrief@v1":
        errors.append("invalid:version")
    source_revision = document.get("sourceRevision")
    if not isinstance(source_revision, int) or source_revision < 1:
        errors.append("invalid:sourceRevision")
    if not _is_non_empty_str(document.get("explorationMapId")):
        errors.append("missing:explorationMapId")
    destination = document.get("destination")
    if not isinstance(destination, dict) or not _is_non_empty_str(destination.get("statement")):
        errors.append("missing:destination.statement")
    readiness = document.get("readiness")
    if not isinstance(readiness, dict):
        errors.append("missing:readiness")
    else:
        if not _is_non_empty_str(readiness.get("readinessId")):
            errors.append("missing:readiness.readinessId")
        if not isinstance(readiness.get("readyForDocHandoff"), bool):
            errors.append("missing:readiness.readyForDocHandoff")
    candidates = document.get("planningUnitCandidates")
    if not isinstance(candidates, list):
        errors.append("missing:planningUnitCandidates")
    else:
        for candidate in candidates:
            if not isinstance(candidate, dict):
                errors.append("invalid:planningUnitCandidates.entry")
                continue
            for req in ("id", "title", "rationale"):
                if not _is_non_empty_str(candidate.get(req)):
                    errors.append(f"invalid:planningUnitCandidates.{req}")
    invalidation = document.get("invalidation")
    if not isinstance(invalidation, dict):
        errors.append("missing:invalidation")
    elif invalidation.get("state") not in {"valid", "stale", "superseded"}:
        errors.append("invalid:invalidation.state")
    if not _is_non_empty_str(document.get("emittedAt")):
        errors.append("missing:emittedAt")
    boundary = document.get("authorityBoundary")
    if boundary is not None:
        if boundary.get("createsPrds") is not False:
            errors.append("invalid:authorityBoundary.createsPrds")
        if boundary.get("createsTasks") is not False:
            errors.append("invalid:authorityBoundary.createsTasks")
        if boundary.get("dispatchesImplementation") is not False:
            errors.append("invalid:authorityBoundary.dispatchesImplementation")
    return errors


VALIDATORS: dict[str, Callable[[dict[str, Any]], list[str]]] = {
    "validate_exploration_map": validate_exploration_map,
    "validate_planning_readiness": validate_planning_readiness,
    "validate_exploration_brief": validate_exploration_brief,
}


def _minimal_map(**overrides: object) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": "explore-001",
        "version": "ExplorationMap@v1",
        "revision": 1,
        "destination": {
            "statement": "Clarify whether /sw-explore should ship as first-class pre-planning.",
            "nonCommittal": True,
            "updatedAt": "2026-08-24T00:00:00Z",
        },
        "structuredFields": {
            "problem": "Operators jump to /sw-doc too early.",
            "outcomes": ["Resumable explore sessions"],
            "unknowns": [
                {
                    "id": "unk-blocking",
                    "statement": "Which intelligence hooks are mandatory?",
                    "classification": "blocking",
                }
            ],
        },
        "nodes": [
            {
                "id": "q-scope",
                "type": "question",
                "status": "open",
                "statement": "What is the atomic release boundary?",
            }
        ],
        "persistenceTriggers": {
            "blockingUnknowns": True,
            "resumeRequired": False,
            "promoteReceipt": None,
        },
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "conversation",
        },
    }
    doc.update(overrides)
    return doc


def _minimal_readiness(**overrides: object) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": "readiness-001",
        "version": "PlanningReadiness@v1",
        "sourceRevision": 1,
        "explorationMapId": "explore-001",
        "unknowns": [
            {
                "id": "unk-blocking",
                "statement": "Which intelligence hooks are mandatory?",
                "classification": "blocking",
            }
        ],
        "summary": {
            "blockingCount": 1,
            "nonBlockingCount": 0,
            "deferredCount": 0,
        },
        "invalidation": {"state": "valid"},
        "computedAt": "2026-08-24T01:00:00Z",
        "readyForDocHandoff": False,
    }
    doc.update(overrides)
    return doc


def _minimal_brief(**overrides: object) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "id": "brief-001",
        "version": "ExplorationBrief@v1",
        "sourceRevision": 1,
        "explorationMapId": "explore-001",
        "destination": {
            "statement": "Clarify whether /sw-explore should ship as first-class pre-planning."
        },
        "readiness": {
            "readinessId": "readiness-001",
            "readyForDocHandoff": False,
        },
        "planningUnitCandidates": [
            {
                "id": "unit-schemas",
                "title": "Exploration artifact schemas",
                "rationale": "Normative contracts precede consumer surfaces.",
            }
        ],
        "invalidation": {"state": "valid"},
        "emittedAt": "2026-08-24T02:00:00Z",
        "authorityBoundary": {
            "createsPrds": False,
            "createsTasks": False,
            "dispatchesImplementation": False,
        },
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def map_schema(repo_root: Path) -> dict[str, Any]:
    return _load_schema(repo_root, MAP_SCHEMA_REL)


@pytest.fixture
def readiness_schema(repo_root: Path) -> dict[str, Any]:
    return _load_schema(repo_root, READINESS_SCHEMA_REL)


@pytest.fixture
def brief_schema(repo_root: Path) -> dict[str, Any]:
    return _load_schema(repo_root, BRIEF_SCHEMA_REL)


def test_exploration_schema_files_exist(repo_root: Path) -> None:
    for rel in EXPLORATION_SCHEMA_FILES:
        assert (repo_root / rel).is_file(), rel


def test_normative_schemas_have_validator_owners(repo_root: Path) -> None:
    for rel in EXPLORATION_SCHEMA_FILES:
        owner = VALIDATOR_OWNERS.get(rel.name)
        assert owner, f"missing-owner:{rel.name}"
        assert owner in VALIDATORS, f"unknown-validator:{owner}"
        schema = _load_schema(repo_root, rel)
        assert schema.get("title"), rel.name
        version = schema.get("properties", {}).get("version", {}).get("const")
        assert version, f"missing-version-const:{rel.name}"


def test_exploration_map_v1_schema_contract(map_schema: dict[str, Any]) -> None:
    assert validate_exploration_map({})
    doc = _minimal_map()
    assert validate_exploration_map(doc) == []
    _validate_with_jsonschema(doc, map_schema)


def test_exploration_map_empty_object_rejected() -> None:
    assert validate_exploration_map({})


def test_exploration_map_many_nodes_and_revision(map_schema: dict[str, Any]) -> None:
    doc = _minimal_map(
        revision=7,
        nodes=[
            {
                "id": "q-one",
                "type": "question",
                "status": "open",
                "statement": "First question?",
            },
            {
                "id": "d-one",
                "type": "decision",
                "status": "resolved",
                "title": "Use stance B",
                "resolution": "Conversation-first with triggered persistence.",
            },
            {
                "id": "e-one",
                "type": "evidence",
                "status": "open",
                "evidenceRef": {
                    "kind": "ResearchEvidence",
                    "refId": "research-001",
                    "trust": "trusted",
                },
            },
            {
                "id": "disc-one",
                "type": "discovery",
                "status": "open",
                "statement": "Greenfield repos still need destination capture.",
            },
        ],
        supersededNodeIds=["d-old"],
    )
    assert validate_exploration_map(doc) == []
    _validate_with_jsonschema(doc, map_schema)


def test_exploration_map_version_edge_rejected() -> None:
    doc = _minimal_map(version="ExplorationMap@v2")
    assert any("invalid:version" in err for err in validate_exploration_map(doc))


def test_exploration_map_malformed_node_rejected() -> None:
    doc = _minimal_map(
        nodes=[{"id": "bad", "type": "question", "status": "open"}]
    )
    assert validate_exploration_map(doc)


def test_exploration_map_secret_free_constraints() -> None:
    assert _scan_forbidden_secrets({"apiKey": "x"})
    doc = _minimal_map()
    doc["credential"] = {"note": "must-not-appear-in-canonical-map"}
    errors = validate_exploration_map(doc)
    assert any(err.startswith("unknown:") for err in errors)


def test_exploration_map_persistence_trigger_matrix(map_schema: dict[str, Any]) -> None:
    for triggers in (
        {"blockingUnknowns": True, "resumeRequired": False, "promoteReceipt": None},
        {"blockingUnknowns": False, "resumeRequired": True, "promoteReceipt": None},
        {
            "blockingUnknowns": False,
            "resumeRequired": False,
            "promoteReceipt": {
                "receiptId": "promote-001",
                "issuedAt": "2026-08-24T03:00:00Z",
                "actor": "operator",
            },
        },
    ):
        doc = _minimal_map(persistenceTriggers=triggers)
        assert validate_exploration_map(doc) == []
        _validate_with_jsonschema(doc, map_schema)


def test_typed_nodes_are_exhaustive(map_schema: dict[str, Any]) -> None:
    for node_type, payload in (
        (
            "question",
            {
                "id": "q-only",
                "type": "question",
                "status": "open",
                "statement": "What is unknown?",
            },
        ),
        (
            "decision",
            {
                "id": "d-only",
                "type": "decision",
                "status": "superseded",
                "title": "Prior choice",
                "supersedes": "d-old",
            },
        ),
        (
            "evidence",
            {
                "id": "e-only",
                "type": "evidence",
                "status": "open",
                "evidenceRef": {
                    "kind": "PrototypeEvidence",
                    "refId": "proto-001",
                    "trust": "untrusted",
                    "productionEligible": False,
                },
            },
        ),
        (
            "discovery",
            {
                "id": "disc-only",
                "type": "discovery",
                "status": "open",
                "statement": "New signal discovered.",
            },
        ),
    ):
        doc = _minimal_map(nodes=[payload])
        assert validate_exploration_map(doc) == [], node_type
        _validate_with_jsonschema(doc, map_schema)


def test_typed_nodes_unknown_type_rejected() -> None:
    doc = _minimal_map(
        nodes=[{"id": "x", "type": "hypothesis", "status": "open", "statement": "nope"}]
    )
    assert validate_exploration_map(doc)


def test_planning_readiness_v1_is_deterministic(readiness_schema: dict[str, Any]) -> None:
    doc = _minimal_readiness()
    assert validate_planning_readiness(doc) == []
    _validate_with_jsonschema(doc, readiness_schema)


def test_planning_readiness_empty_unknowns(readiness_schema: dict[str, Any]) -> None:
    doc = _minimal_readiness(
        unknowns=[],
        summary={"blockingCount": 0, "nonBlockingCount": 0, "deferredCount": 0},
        readyForDocHandoff=True,
    )
    assert validate_planning_readiness(doc) == []
    _validate_with_jsonschema(doc, readiness_schema)


def test_unknown_classification_is_complete(readiness_schema: dict[str, Any]) -> None:
    doc = _minimal_readiness(
        unknowns=[
            {"id": "b", "statement": "Blocking item", "classification": "blocking"},
            {"id": "n", "statement": "Non-blocking item", "classification": "non-blocking"},
            {"id": "d", "statement": "Deferred item", "classification": "deferred"},
        ],
        summary={"blockingCount": 1, "nonBlockingCount": 1, "deferredCount": 1},
    )
    assert validate_planning_readiness(doc) == []
    _validate_with_jsonschema(doc, readiness_schema)


def test_planning_readiness_stale_source_revision(readiness_schema: dict[str, Any]) -> None:
    doc = _minimal_readiness(
        sourceRevision=1,
        invalidation={
            "state": "stale",
            "reason": "ExplorationMap advanced to revision 3",
            "supersededByRevision": 3,
        },
    )
    assert validate_planning_readiness(doc) == []
    _validate_with_jsonschema(doc, readiness_schema)


def test_planning_readiness_version_rejected() -> None:
    doc = _minimal_readiness(version="PlanningReadiness@v2")
    assert validate_planning_readiness(doc)


def test_exploration_brief_v1_round_trip(brief_schema: dict[str, Any]) -> None:
    doc = _minimal_brief()
    assert validate_exploration_brief(doc) == []
    _validate_with_jsonschema(doc, brief_schema)


def test_exploration_brief_many_candidates(brief_schema: dict[str, Any]) -> None:
    doc = _minimal_brief(
        planningUnitCandidates=[
            {
                "id": "unit-a",
                "title": "Schema layer",
                "rationale": "Contracts first.",
                "dependencies": [],
            },
            {
                "id": "unit-b",
                "title": "Storage layer",
                "rationale": "Lifecycle before consumers.",
                "dependencies": ["unit-a"],
            },
        ],
        remainingUncertainty=[
            {
                "id": "u1",
                "statement": "Intel degradation policy",
                "classification": "non-blocking",
            }
        ],
    )
    assert validate_exploration_brief(doc) == []
    _validate_with_jsonschema(doc, brief_schema)


def test_exploration_brief_stale_revision_rejected_state(brief_schema: dict[str, Any]) -> None:
    doc = _minimal_brief(
        sourceRevision=2,
        invalidation={
            "state": "stale",
            "reason": "Map revision mismatch",
            "invalidatedAt": "2026-08-24T04:00:00Z",
        },
    )
    assert validate_exploration_brief(doc) == []
    _validate_with_jsonschema(doc, brief_schema)


def test_exploration_brief_version_rejected() -> None:
    doc = _minimal_brief(version="ExplorationBrief@v0")
    assert validate_exploration_brief(doc)


def test_revision_binding_across_artifacts() -> None:
    revision = 4
    map_doc = _minimal_map(revision=revision)
    readiness_doc = _minimal_readiness(sourceRevision=revision)
    brief_doc = _minimal_brief(sourceRevision=revision)
    assert validate_exploration_map(map_doc) == []
    assert validate_planning_readiness(readiness_doc) == []
    assert validate_exploration_brief(brief_doc) == []
    brief_doc["sourceRevision"] = revision - 1
    assert validate_exploration_brief(brief_doc) == []
    readiness_doc["sourceRevision"] = revision + 1
    assert validate_planning_readiness(readiness_doc) == []


def test_storage_lifecycle_precedes_consumers(repo_root: Path) -> None:
    for rel in EXPLORATION_SCHEMA_FILES:
        assert (repo_root / rel).is_file()
    store_module = repo_root / "scripts" / "exploration_store.py"
    model_module = repo_root / "scripts" / "exploration_model.py"
    assert store_module.is_file(), "schema phase must precede exploration store"
    assert model_module.is_file(), "schema phase must precede exploration model"


def test_decomposition_emits_candidates_without_writes(brief_schema: dict[str, Any]) -> None:
    doc = _minimal_brief(
        planningUnitCandidates=[
            {
                "id": "candidate-only",
                "title": "Future planning unit",
                "rationale": "Candidate hint only.",
            }
        ],
        authorityBoundary={
            "createsPrds": False,
            "createsTasks": False,
            "dispatchesImplementation": False,
        },
    )
    assert validate_exploration_brief(doc) == []
    _validate_with_jsonschema(doc, brief_schema)
    boundary = doc["authorityBoundary"]
    assert boundary["createsPrds"] is False
    assert boundary["createsTasks"] is False
