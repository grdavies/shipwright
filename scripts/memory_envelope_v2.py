#!/usr/bin/env python3
"""Canonical memory envelope v2 codec (PRD 082 R29).

Typed envelope for distilled memory records across provider adapters. Supersession creates a
new envelope and marks the prior record superseded — no mutation-in-place.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Literal

SCHEMA_VERSION = 2
V1_SCHEMA_VERSION = 1

EnvelopeStatus = Literal["active", "superseded"]
Sensitivity = Literal["public", "internal", "private", "secret"]

STATUSES: frozenset[str] = frozenset({"active", "superseded"})
SENSITIVITIES: frozenset[str] = frozenset({"public", "internal", "private", "secret"})
ISO_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

REQUIRED_FIELDS: frozenset[str] = frozenset(
    {
        "stableId",
        "projectId",
        "category",
        "status",
        "scope",
        "evidenceRefs",
        "confidence",
        "observedAt",
        "lastValidatedAt",
        "validUntil",
        "supersedes",
        "contentHash",
        "schemaVersion",
        "sensitivity",
        "appliedRedaction",
    }
)

PLANNING_BODY_MARKERS = frozenset({"planning-body", "planning_body"})


class EnvelopeError(ValueError):
    """Raised when an envelope fails schema validation."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_content_hash(content: dict[str, Any]) -> str:
    """Stable SHA-256 over envelope semantic content (excludes contentHash itself)."""
    body = {k: v for k, v in content.items() if k != "contentHash"}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def empty_applied_redaction() -> dict[str, Any]:
    return {
        "applied": False,
        "profile": None,
        "redactedAt": None,
        "redactionScript": "scripts/memory-redact.py",
    }


def empty_scope() -> dict[str, Any]:
    return {"repos": [], "paths": [], "tags": []}


def _validate_iso_timestamp(value: Any, field: str, errors: list[str], *, required: bool) -> None:
    if value is None:
        if required:
            errors.append(f"{field}:required")
        return
    if not isinstance(value, str) or not ISO_TS_RE.match(value):
        errors.append(f"{field}:invalid-timestamp")


def _validate_applied_redaction(value: Any, errors: list[str]) -> None:
    if not isinstance(value, dict):
        errors.append("appliedRedaction:invalid")
        return
    if not isinstance(value.get("applied"), bool):
        errors.append("appliedRedaction.applied:invalid")
    if "redactionScript" in value and value["redactionScript"] is not None:
        if not isinstance(value["redactionScript"], str):
            errors.append("appliedRedaction.redactionScript:invalid")


def validate_envelope(doc: Any) -> list[str]:
    """Return a list of validation error codes; empty means valid."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["envelope:not-object"]

    version = doc.get("schemaVersion")
    if version != SCHEMA_VERSION:
        errors.append("schemaVersion:invalid")

    for field in REQUIRED_FIELDS:
        if field not in doc:
            errors.append(f"{field}:missing")

    stable_id = doc.get("stableId")
    if stable_id is not None and (not isinstance(stable_id, str) or not stable_id.strip()):
        errors.append("stableId:invalid")

    project_id = doc.get("projectId")
    if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
        errors.append("projectId:invalid")

    category = doc.get("category")
    if category is not None and (not isinstance(category, str) or not category.strip()):
        errors.append("category:invalid")

    status = doc.get("status")
    if status not in STATUSES:
        errors.append("status:invalid")

    scope = doc.get("scope")
    if scope is not None and not isinstance(scope, dict):
        errors.append("scope:invalid")

    evidence = doc.get("evidenceRefs")
    if evidence is not None:
        if not isinstance(evidence, list) or any(not isinstance(x, str) for x in evidence):
            errors.append("evidenceRefs:invalid")

    confidence = doc.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            errors.append("confidence:invalid")

    _validate_iso_timestamp(doc.get("observedAt"), "observedAt", errors, required=True)
    _validate_iso_timestamp(doc.get("lastValidatedAt"), "lastValidatedAt", errors, required=False)
    _validate_iso_timestamp(doc.get("validUntil"), "validUntil", errors, required=False)

    supersedes = doc.get("supersedes")
    if supersedes is not None:
        if not isinstance(supersedes, list) or any(not isinstance(x, str) for x in supersedes):
            errors.append("supersedes:invalid")

    content_hash = doc.get("contentHash")
    if content_hash is not None:
        if not isinstance(content_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", content_hash):
            errors.append("contentHash:invalid")

    sensitivity = doc.get("sensitivity")
    if sensitivity not in SENSITIVITIES:
        errors.append("sensitivity:invalid")

    _validate_applied_redaction(doc.get("appliedRedaction"), errors)

    if not errors and content_hash is not None:
        expected = compute_content_hash(doc)
        if content_hash != expected:
            errors.append("contentHash:mismatch")

    return errors


def parse_envelope(doc: Any) -> dict[str, Any]:
    errors = validate_envelope(doc)
    if errors:
        raise EnvelopeError("; ".join(errors))
    return dict(doc)


def new_envelope(
    *,
    stable_id: str,
    project_id: str,
    category: str,
    status: EnvelopeStatus = "active",
    scope: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
    confidence: float = 0.5,
    observed_at: str | None = None,
    last_validated_at: str | None = None,
    valid_until: str | None = None,
    supersedes: list[str] | None = None,
    sensitivity: Sensitivity = "internal",
    applied_redaction: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct a v2 envelope and stamp contentHash."""
    doc: dict[str, Any] = {
        "stableId": stable_id,
        "projectId": project_id,
        "category": category,
        "status": status,
        "scope": scope if scope is not None else empty_scope(),
        "evidenceRefs": list(evidence_refs or []),
        "confidence": float(confidence),
        "observedAt": observed_at or utc_now_iso(),
        "lastValidatedAt": last_validated_at,
        "validUntil": valid_until,
        "supersedes": list(supersedes or []),
        "schemaVersion": SCHEMA_VERSION,
        "sensitivity": sensitivity,
        "appliedRedaction": applied_redaction if applied_redaction is not None else empty_applied_redaction(),
    }
    if payload:
        doc["payload"] = payload
    doc["contentHash"] = compute_content_hash(doc)
    errors = validate_envelope(doc)
    if errors:
        raise EnvelopeError("; ".join(errors))
    return doc


def supersede(
    current: dict[str, Any],
    *,
    replacement_id: str,
    updates: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Mark current superseded and return (superseded_copy, new_active_envelope)."""
    active = parse_envelope(current)
    if active["status"] != "active":
        raise EnvelopeError("supersede:source-not-active")

    superseded_copy = dict(active)
    superseded_copy["status"] = "superseded"
    superseded_copy["contentHash"] = compute_content_hash(superseded_copy)

    merged = {
        "stableId": replacement_id,
        "projectId": active["projectId"],
        "category": active["category"],
        "status": "active",
        "scope": dict(active.get("scope") or empty_scope()),
        "evidenceRefs": list(active.get("evidenceRefs") or []),
        "confidence": active.get("confidence", 0.5),
        "observedAt": utc_now_iso(),
        "lastValidatedAt": active.get("lastValidatedAt"),
        "validUntil": active.get("validUntil"),
        "supersedes": [active["stableId"]],
        "sensitivity": active.get("sensitivity", "internal"),
        "appliedRedaction": dict(active.get("appliedRedaction") or empty_applied_redaction()),
    }
    if "payload" in active:
        merged["payload"] = dict(active["payload"])
    if updates:
        merged.update(updates)
        merged["supersedes"] = list(merged.get("supersedes") or [active["stableId"]])
    replacement = new_envelope(**_kwargs_from_envelope(merged))
    return superseded_copy, replacement


def _kwargs_from_envelope(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "stable_id": doc["stableId"],
        "project_id": doc["projectId"],
        "category": doc["category"],
        "status": doc.get("status", "active"),
        "scope": doc.get("scope"),
        "evidence_refs": doc.get("evidenceRefs"),
        "confidence": doc.get("confidence", 0.5),
        "observed_at": doc.get("observedAt"),
        "last_validated_at": doc.get("lastValidatedAt"),
        "valid_until": doc.get("validUntil"),
        "supersedes": doc.get("supersedes"),
        "sensitivity": doc.get("sensitivity", "internal"),
        "applied_redaction": doc.get("appliedRedaction"),
        "payload": doc.get("payload"),
    }


def resolve_supersession_chain(
    envelopes: dict[str, dict[str, Any]],
    stable_id: str,
    *,
    max_hops: int = 64,
) -> str:
    """Follow supersedes edges forward to the active tip id."""
    seen: set[str] = set()
    current = stable_id
    for _ in range(max_hops):
        if current in seen:
            raise EnvelopeError("supersession:cycle")
        seen.add(current)
        doc = envelopes.get(current)
        if doc is None:
            return current
        parsed = parse_envelope(doc)
        if parsed["status"] == "active":
            return current
        successors = [
            sid
            for sid, env in envelopes.items()
            if sid not in seen
            and isinstance(env, dict)
            and current in (env.get("supersedes") or [])
            and env.get("status") == "active"
        ]
        if not successors:
            return current
        if len(successors) > 1:
            raise EnvelopeError("supersession:ambiguous")
        current = successors[0]
    raise EnvelopeError("supersession:max-hops")


def is_planning_body_payload(payload: Any) -> bool:
    """Planning bodies are outside the v2 memory envelope record domain (R29)."""
    if not isinstance(payload, dict):
        return False
    domain = str(payload.get("domain") or payload.get("kind") or "").lower()
    if domain in PLANNING_BODY_MARKERS:
        return True
    if payload.get("planningBody") is True:
        return True
    unit_id = payload.get("unitId")
    body = payload.get("body")
    if isinstance(unit_id, str) and unit_id.strip() and isinstance(body, str):
        if payload.get("schemaVersion") is None and payload.get("stableId") is None:
            return True
    return False


def envelope_required(payload: Any) -> bool:
    """True when payload must be wrapped in a v2 envelope before adapter persistence."""
    if is_planning_body_payload(payload):
        return False
    if isinstance(payload, dict) and payload.get("schemaVersion") == SCHEMA_VERSION:
        return False
    return isinstance(payload, dict) and bool(payload)
