#!/usr/bin/env python3
"""Bind exploration nodes to existing ResearchEvidence / PrototypeEvidence contracts (PRD 331 R10, R43, R44)."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from decision_graph.evidence import (
    KIND_PROTOTYPE,
    KIND_RESEARCH,
    EvidenceSchemaError,
    build_evidence_record,
    build_research_evidence_record,
    linked_evidence_records,
    validate_research_evidence_record,
    write_evidence_record,
)

ALLOWED_EVIDENCE_KINDS = frozenset({KIND_RESEARCH, KIND_PROTOTYPE})
TRUST_VALUES = frozenset({"trusted", "untrusted"})


class ExplorationEvidenceError(ValueError):
    """Invalid exploration evidence binding."""


def evidence_ref_id(record: Mapping[str, Any]) -> str:
    """Stable ref id derived from the canonical evidence record (no parallel silo)."""
    kind = str(record.get("kind") or "")
    if kind not in ALLOWED_EVIDENCE_KINDS:
        raise ExplorationEvidenceError("unsupported-evidence-kind")
    spec = record.get("spec")
    if not isinstance(spec, dict):
        raise ExplorationEvidenceError("invalid-evidence-spec")
    content_hash = str(spec.get("contentHash") or "")
    if content_hash:
        return content_hash
    head_sha = str(spec.get("headSha") or "")
    if head_sha:
        return head_sha
    raise ExplorationEvidenceError("missing-evidence-digest")


def build_evidence_ref(
    record: Mapping[str, Any],
    *,
    trust: str = "trusted",
) -> dict[str, Any]:
    """Build an ExplorationMap evidenceRef from an existing evidence record (R10)."""
    kind = str(record.get("kind") or "")
    if kind not in ALLOWED_EVIDENCE_KINDS:
        raise ExplorationEvidenceError("unsupported-evidence-kind")
    if trust not in TRUST_VALUES:
        raise ExplorationEvidenceError("invalid-trust")
    ref: dict[str, Any] = {
        "kind": kind,
        "refId": evidence_ref_id(record),
        "trust": trust,
    }
    if kind == KIND_PROTOTYPE:
        ref["productionEligible"] = False
    return ref


def is_production_eligible(evidence_ref: Mapping[str, Any]) -> bool:
    """Prototype evidence is never production-eligible (R44)."""
    kind = str(evidence_ref.get("kind") or "")
    if kind == KIND_PROTOTYPE:
        return False
    if evidence_ref.get("productionEligible") is False:
        return False
    return kind == KIND_RESEARCH


def validate_evidence_ref(evidence_ref: Mapping[str, Any]) -> None:
    kind = str(evidence_ref.get("kind") or "")
    if kind not in ALLOWED_EVIDENCE_KINDS:
        raise ExplorationEvidenceError("parallel-evidence-silo")
    ref_id = str(evidence_ref.get("refId") or "").strip()
    if not ref_id:
        raise ExplorationEvidenceError("missing-ref-id")
    trust = str(evidence_ref.get("trust") or "")
    if trust not in TRUST_VALUES:
        raise ExplorationEvidenceError("invalid-trust")
    if kind == KIND_PROTOTYPE and evidence_ref.get("productionEligible") is not False:
        raise ExplorationEvidenceError("prototype-must-be-non-production")


def resolve_evidence_record(
    root: Path,
    evidence_ref: Mapping[str, Any],
    *,
    parent_decision_id: str | None = None,
) -> dict[str, Any] | None:
    """Resolve an exploration evidenceRef to the canonical stored record."""
    validate_evidence_ref(evidence_ref)
    kind = str(evidence_ref["kind"])
    ref_id = str(evidence_ref["refId"])
    if parent_decision_id:
        for record in linked_evidence_records(root, parent_decision_id, kind):
            if evidence_ref_id(record) == ref_id:
                return record
    base = root / ".cursor" / "sw-decision-evidence"
    if not base.is_dir():
        return None
    for path in base.rglob("*.json"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(document, dict):
            continue
        if str(document.get("kind") or "") != kind:
            continue
        if evidence_ref_id(document) == ref_id:
            return document
    return None


def bind_evidence_node(
    node: Mapping[str, Any],
    record: Mapping[str, Any],
    *,
    trust: str = "trusted",
) -> dict[str, Any]:
    """Attach canonical evidence to an exploration evidence node."""
    if str(node.get("type") or "") != "evidence":
        raise ExplorationEvidenceError("node-not-evidence")
    updated = deepcopy(dict(node))
    updated["evidenceRef"] = build_evidence_ref(record, trust=trust)
    updated.setdefault("status", "resolved")
    return updated


def bind_research_evidence(
    root: Path,
    *,
    parent_decision_id: str,
    claim: str,
    sources: list[dict[str, Any]],
    source_kind: str,
    trust: str = "trusted",
    persist: bool = True,
) -> dict[str, Any]:
    record = build_research_evidence_record(
        parent_decision_id=parent_decision_id,
        claim=claim,
        sources=sources,
        source_kind=source_kind,
    )
    if persist:
        write_evidence_record(root, record)
    return {
        "verdict": "ok",
        "record": record,
        "evidenceRef": build_evidence_ref(record, trust=trust),
    }


def bind_prototype_evidence(
    root: Path,
    *,
    parent_decision_id: str,
    prototype_node_id: str,
    head_sha: str,
    content_hash: str,
    branch: str,
    trust: str = "untrusted",
    persist: bool = True,
) -> dict[str, Any]:
    record = build_evidence_record(
        parent_decision_id=parent_decision_id,
        prototype_node_id=prototype_node_id,
        head_sha=head_sha,
        content_hash=content_hash,
        branch=branch,
    )
    if persist:
        write_evidence_record(root, record)
    return {
        "verdict": "ok",
        "record": record,
        "evidenceRef": build_evidence_ref(record, trust=trust),
    }


def attach_evidence_to_map(
    map_document: Mapping[str, Any],
    *,
    node_id: str,
    record: Mapping[str, Any],
    trust: str = "trusted",
) -> dict[str, Any]:
    """Bind an existing evidence record onto a map evidence node by id."""
    nodes = [deepcopy(node) for node in map_document.get("nodes") or [] if isinstance(node, dict)]
    updated_map = deepcopy(dict(map_document))
    found = False
    for index, node in enumerate(nodes):
        if node.get("id") != node_id:
            continue
        nodes[index] = bind_evidence_node(node, record, trust=trust)
        found = True
        break
    if not found:
        raise ExplorationEvidenceError("evidence-node-not-found")
    updated_map["nodes"] = nodes
    return updated_map


def summarize_evidence_bindings(map_document: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize trusted/untrusted evidence bindings for status projection."""
    trusted = 0
    untrusted = 0
    prototypes = 0
    for node in map_document.get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "evidence":
            continue
        evidence_ref = node.get("evidenceRef")
        if not isinstance(evidence_ref, dict):
            continue
        validate_evidence_ref(evidence_ref)
        if evidence_ref.get("kind") == KIND_PROTOTYPE:
            prototypes += 1
        if evidence_ref.get("trust") == "trusted":
            trusted += 1
        else:
            untrusted += 1
    return {
        "trusted": trusted,
        "untrusted": untrusted,
        "prototypeEvidence": prototypes,
        "productionEligible": False if prototypes else None,
    }


def digest_record(record: Mapping[str, Any]) -> str:
    """Deterministic digest for duplicate-schema detection."""
    return hashlib.sha256(
        json.dumps(
            {"kind": record.get("kind"), "apiVersion": record.get("apiVersion")},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def assert_canonical_evidence_schema(record: Mapping[str, Any]) -> None:
    """Refuse parallel evidence silos — only canonical kinds/schemas (R10)."""
    kind = str(record.get("kind") or "")
    if kind == KIND_RESEARCH:
        validate_research_evidence_record(dict(record))
        return
    if kind == KIND_PROTOTYPE:
        if record.get("apiVersion") != "decision-evidence/v1":
            raise EvidenceSchemaError("invalid apiVersion", path=["apiVersion"])
        return
    raise ExplorationEvidenceError("parallel-evidence-silo")
