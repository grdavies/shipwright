"""PRD 330 R9, R10, R14 — ProjectDoctrine@v1 and ProjectBaseline@v1 schema fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

DOCTRINE_SCHEMA_REL = Path("core/sw-reference/project-doctrine.schema.json")
BASELINE_SCHEMA_REL = Path("core/sw-reference/project-baseline.schema.json")

DOCTRINE_FORBIDDEN_ROOT = frozenset(
    {"productRoadmap", "orgChart", "runtimeRunbook"}
)
BASELINE_FORBIDDEN_ROOT = frozenset(
    {"doctrineAuthority", "productAuthority", "autonomousPromotion", "promoted"}
)
CONFIDENCE_VALUES = frozenset({"high", "medium", "low", "unknown"})


def _load_schema(repo_root: Path, rel: Path) -> dict:
    return json.loads((repo_root / rel).read_text(encoding="utf-8"))


def _is_non_empty_str(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_doctrine(document: dict) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "provenance",
        "confidence",
        "expiresAt",
        "sourceRefs",
        "architecture",
        "assessment",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    for key in DOCTRINE_FORBIDDEN_ROOT:
        if key in document:
            errors.append(f"forbidden:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "ProjectDoctrine@v1":
        errors.append("invalid:version")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing:provenance")
    else:
        if not _is_non_empty_str(provenance.get("createdAt")):
            errors.append("missing:provenance.createdAt")
        if not _is_non_empty_str(provenance.get("source")):
            errors.append("missing:provenance.source")
    has_confidence = document.get("confidence") in CONFIDENCE_VALUES
    has_expiry = _is_non_empty_str(document.get("expiresAt"))
    if not has_confidence and not has_expiry:
        errors.append("missing:confidence-or-expiresAt")
    source_refs = document.get("sourceRefs")
    if not isinstance(source_refs, list) or not source_refs:
        errors.append("missing:sourceRefs")
    elif not all(
        isinstance(ref, dict) and _is_non_empty_str(ref.get("uri")) for ref in source_refs
    ):
        errors.append("invalid:sourceRefs")
    architecture = document.get("architecture")
    if architecture is not None:
        if not isinstance(architecture, dict):
            errors.append("invalid:architecture")
        else:
            for bucket in ("modules", "interfaces", "seams", "adapters", "locality"):
                items = architecture.get(bucket)
                if items is None:
                    continue
                if not isinstance(items, list):
                    errors.append(f"invalid:architecture.{bucket}")
                    continue
                for entry in items:
                    if not isinstance(entry, dict):
                        errors.append(f"invalid:architecture.{bucket}.entry")
                        continue
                    if not _is_non_empty_str(entry.get("id")) or not _is_non_empty_str(
                        entry.get("name")
                    ):
                        errors.append(f"invalid:architecture.{bucket}.entry")
    assessment = document.get("assessment")
    if assessment is not None and not isinstance(assessment, dict):
        errors.append("invalid:assessment")
    return errors


def _validate_baseline(document: dict) -> list[str]:
    errors: list[str] = []
    allowed = {
        "id",
        "version",
        "provenance",
        "status",
        "confidence",
        "expiresAt",
        "facts",
        "conflicts",
    }
    for key in document:
        if key not in allowed:
            errors.append(f"unknown:{key}")
    for key in BASELINE_FORBIDDEN_ROOT:
        if key in document:
            errors.append(f"forbidden:{key}")
    if not _is_non_empty_str(document.get("id")):
        errors.append("missing:id")
    if document.get("version") != "ProjectBaseline@v1":
        errors.append("invalid:version")
    if document.get("status") != "draft":
        errors.append("invalid:status")
    provenance = document.get("provenance")
    if not isinstance(provenance, dict):
        errors.append("missing:provenance")
    else:
        if not _is_non_empty_str(provenance.get("createdAt")):
            errors.append("missing:provenance.createdAt")
        if not _is_non_empty_str(provenance.get("source")):
            errors.append("missing:provenance.source")
    has_confidence = document.get("confidence") in CONFIDENCE_VALUES
    has_expiry = _is_non_empty_str(document.get("expiresAt"))
    if not has_confidence and not has_expiry:
        errors.append("missing:confidence-or-expiresAt")
    facts = document.get("facts")
    if not isinstance(facts, list):
        errors.append("missing:facts")
    else:
        for fact in facts:
            if not isinstance(fact, dict):
                errors.append("invalid:facts.entry")
                continue
            if not _is_non_empty_str(fact.get("id")) or not _is_non_empty_str(fact.get("claim")):
                errors.append("invalid:facts.entry")
            evidence = fact.get("sourceEvidence")
            if not isinstance(evidence, dict) or not _is_non_empty_str(evidence.get("uri")):
                errors.append("invalid:facts.sourceEvidence")
            fact_conf = fact.get("confidence") in CONFIDENCE_VALUES
            fact_exp = _is_non_empty_str(fact.get("expiresAt"))
            if not fact_conf and not fact_exp:
                errors.append("invalid:facts.confidence-or-expiresAt")
    conflicts = document.get("conflicts")
    if conflicts is not None:
        if not isinstance(conflicts, list):
            errors.append("invalid:conflicts")
        else:
            for conflict in conflicts:
                if not isinstance(conflict, dict):
                    errors.append("invalid:conflicts.entry")
                    continue
                if not _is_non_empty_str(conflict.get("id")):
                    errors.append("invalid:conflicts.id")
                if conflict.get("status") not in {"open", "acknowledged"}:
                    errors.append("invalid:conflicts.status")
                observations = conflict.get("observations")
                if not isinstance(observations, list) or len(observations) < 2:
                    errors.append("invalid:conflicts.observations")
                    continue
                for obs in observations:
                    if not isinstance(obs, dict):
                        errors.append("invalid:conflicts.observation")
                        continue
                    if not _is_non_empty_str(obs.get("factId")) or not _is_non_empty_str(
                        obs.get("claim")
                    ):
                        errors.append("invalid:conflicts.observation")
                    evidence = obs.get("sourceEvidence")
                    if not isinstance(evidence, dict) or not _is_non_empty_str(
                        evidence.get("uri")
                    ):
                        errors.append("invalid:conflicts.observation.sourceEvidence")
    return errors


def _validate_with_jsonschema(document: dict, schema: dict) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(document, schema, cls=jsonschema.Draft202012Validator)


def _minimal_doctrine(**overrides: object) -> dict:
    doc = {
        "id": "consumer-doctrine",
        "version": "ProjectDoctrine@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "operator-review",
        },
        "confidence": "high",
        "sourceRefs": [{"uri": "file://repo/README.md"}],
    }
    doc.update(overrides)
    return doc


def _minimal_baseline(**overrides: object) -> dict:
    doc = {
        "id": "consumer-baseline",
        "version": "ProjectBaseline@v1",
        "provenance": {
            "createdAt": "2026-08-24T00:00:00Z",
            "source": "baseline-synthesis",
        },
        "status": "draft",
        "confidence": "medium",
        "facts": [
            {
                "id": "fact-1",
                "claim": "Primary runtime is Python 3.",
                "sourceEvidence": {"uri": "file://repo/pyproject.toml"},
                "confidence": "high",
            }
        ],
    }
    doc.update(overrides)
    return doc


@pytest.fixture
def doctrine_schema(repo_root: Path) -> dict:
    return _load_schema(repo_root, DOCTRINE_SCHEMA_REL)


@pytest.fixture
def baseline_schema(repo_root: Path) -> dict:
    return _load_schema(repo_root, BASELINE_SCHEMA_REL)


def test_doctrine_schema_files_exist(repo_root: Path) -> None:
    assert (repo_root / DOCTRINE_SCHEMA_REL).is_file()
    assert (repo_root / BASELINE_SCHEMA_REL).is_file()


def test_doctrine_empty_object_rejected() -> None:
    assert _validate_doctrine({})


def test_doctrine_minimum_fields_with_confidence(doctrine_schema: dict) -> None:
    doc = _minimal_doctrine()
    assert _validate_doctrine(doc) == []
    _validate_with_jsonschema(doc, doctrine_schema)


def test_doctrine_expires_at_alternative_to_confidence(doctrine_schema: dict) -> None:
    doc = _minimal_doctrine()
    doc.pop("confidence", None)
    doc["expiresAt"] = "2027-01-01T00:00:00Z"
    assert _validate_doctrine(doc) == []
    _validate_with_jsonschema(doc, doctrine_schema)


def test_doctrine_multiple_source_refs(doctrine_schema: dict) -> None:
    doc = _minimal_doctrine(
        sourceRefs=[
            {"uri": "file://repo/README.md", "label": "readme"},
            {
                "uri": "file://repo/docs/architecture.md",
                "digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            },
        ]
    )
    assert _validate_doctrine(doc) == []
    _validate_with_jsonschema(doc, doctrine_schema)


def test_doctrine_architecture_vocabulary_and_assessment(doctrine_schema: dict) -> None:
    doc = _minimal_doctrine(
        architecture={
            "modules": [{"id": "mod-api", "name": "API layer"}],
            "interfaces": [{"id": "iface-http", "name": "HTTP handlers"}],
            "seams": [{"id": "seam-db", "name": "Database boundary"}],
            "adapters": [{"id": "adapter-queue", "name": "Queue adapter"}],
            "locality": [{"id": "loc-worker", "name": "Worker locality", "locality": "edge"}],
        },
        assessment={
            "artifactPath": ".cursor/architecture-assessment.yaml",
            "doctrineVersion": 1,
            "lastAssessedAt": "2026-08-24T12:00:00Z",
            "entries": [{"id": "AD-1", "verdict": "pass"}],
        },
    )
    assert _validate_doctrine(doc) == []
    _validate_with_jsonschema(doc, doctrine_schema)


def test_doctrine_missing_id_version_or_provenance_rejected() -> None:
    doc = _minimal_doctrine()
    doc.pop("id")
    assert _validate_doctrine(doc)
    doc = _minimal_doctrine()
    doc["version"] = "ProjectDoctrine@v2"
    assert _validate_doctrine(doc)
    doc = _minimal_doctrine()
    doc.pop("provenance")
    assert _validate_doctrine(doc)


def test_doctrine_excluded_product_ops_authority_rejected() -> None:
    for forbidden in (
        {"productRoadmap": {"milestones": []}},
        {"orgChart": {"nodes": []}},
        {"runtimeRunbook": {"steps": []}},
    ):
        doc = _minimal_doctrine(**forbidden)
        errors = _validate_doctrine(doc)
        assert any(err.startswith("forbidden:") or err.startswith("unknown:") for err in errors)


def test_baseline_minimum_draft_with_evidence(baseline_schema: dict) -> None:
    doc = _minimal_baseline()
    assert _validate_baseline(doc) == []
    _validate_with_jsonschema(doc, baseline_schema)


def test_baseline_fact_requires_source_evidence() -> None:
    doc = _minimal_baseline(
        facts=[{"id": "fact-1", "claim": "Missing evidence", "confidence": "low"}]
    )
    assert _validate_baseline(doc)


def test_baseline_conflicts_preserved(baseline_schema: dict) -> None:
    doc = _minimal_baseline(
        conflicts=[
            {
                "id": "conflict-runtime",
                "status": "open",
                "observations": [
                    {
                        "factId": "fact-a",
                        "claim": "Service is sync.",
                        "sourceEvidence": {"uri": "file://repo/docs/a.md"},
                    },
                    {
                        "factId": "fact-b",
                        "claim": "Service is async.",
                        "sourceEvidence": {"uri": "file://repo/docs/b.md"},
                    },
                ],
            }
        ]
    )
    assert _validate_baseline(doc) == []
    _validate_with_jsonschema(doc, baseline_schema)


def test_baseline_expires_at_without_root_confidence(baseline_schema: dict) -> None:
    doc = _minimal_baseline()
    doc.pop("confidence", None)
    doc["expiresAt"] = "2027-06-01T00:00:00Z"
    assert _validate_baseline(doc) == []
    _validate_with_jsonschema(doc, baseline_schema)


def test_baseline_fact_expires_at_alternative(baseline_schema: dict) -> None:
    doc = _minimal_baseline(
        facts=[
            {
                "id": "fact-1",
                "claim": "Expiry-only fact.",
                "sourceEvidence": {"uri": "file://repo/README.md"},
                "expiresAt": "2027-01-01T00:00:00Z",
            }
        ]
    )
    assert _validate_baseline(doc) == []
    _validate_with_jsonschema(doc, baseline_schema)


def test_baseline_autonomous_authority_fields_rejected() -> None:
    for forbidden in (
        {"doctrineAuthority": True},
        {"productAuthority": True},
        {"autonomousPromotion": True},
        {"promoted": True},
    ):
        doc = _minimal_baseline(**forbidden)
        errors = _validate_baseline(doc)
        assert any(err.startswith("forbidden:") or err.startswith("unknown:") for err in errors)


def test_baseline_non_draft_status_rejected() -> None:
    doc = _minimal_baseline(status="promoted")
    assert _validate_baseline(doc)
