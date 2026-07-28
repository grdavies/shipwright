#!/usr/bin/env python3
"""Memory note fingerprint for deduplication (PRD 082 R29).

Computes a stable SHA-256 fingerprint over semantic envelope content using a
named field allowlist. Envelope-evolution fields (schema version, content hash,
validity, status, sensitivity, evidence, supersession, redaction) are excluded
so upgrades and metadata changes never fork record identity.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from memory_envelope_upgrade import upgrade_if_needed

# Named allowlist — only these top-level keys participate in dedup identity.
NOTE_FINGERPRINT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "stableId",
        "projectId",
        "category",
        "scope",
        "confidence",
        "observedAt",
        "lastValidatedAt",
        "payload",
        "v1Preserved",
    }
)

# Optional envelope fields omitted when they match upgrade/population defaults.
_DEFAULT_SCOPE: dict[str, Any] = {"repos": [], "paths": [], "tags": []}
_DEFAULT_CONFIDENCE = 0.5


def _include_optional_allowlist_field(record: dict[str, Any], key: str, value: Any) -> bool:
    if value is None:
        return False
    if key == "scope" and value == _DEFAULT_SCOPE:
        return False
    if key == "confidence" and value == _DEFAULT_CONFIDENCE:
        return "confidence" in record and record.get("schemaVersion") == 1
    if key in ("observedAt", "lastValidatedAt"):
        return record.get("schemaVersion") == 1 and key in record
    return True

# Envelope-evolution fields excluded even when nested aliases appear.
FINGERPRINT_EXCLUDED: frozenset[str] = frozenset(
    {
        "schemaVersion",
        "contentHash",
        "validUntil",
        "status",
        "sensitivity",
        "evidence",
        "evidenceRefs",
        "supersedes",
        "redaction",
        "appliedRedaction",
    }
)

INTERCHANGE_FIELD_ALLOWLIST: frozenset[str] = frozenset(
    {
        "id",
        "category",
        "body",
        "fields",
    }
)

INTERCHANGE_FIELD_EXCLUDED: frozenset[str] = frozenset(
    {
        "id",
        "updatedAt",
        "createdAt",
    }
)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _semantic_payload(record: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(record.get("payload"), dict):
        return dict(record["payload"])
    if record.get("content") is not None:
        return {"content": record["content"]}
    if record.get("body") is not None and "category" not in record:
        return {"body": record["body"]}
    return None


V1_KNOWN_SEMANTIC_KEYS: frozenset[str] = frozenset(
    {
        "schemaVersion",
        "id",
        "stableId",
        "projectId",
        "project",
        "category",
        "status",
        "scope",
        "evidenceRefs",
        "evidence",
        "confidence",
        "observedAt",
        "lastValidatedAt",
        "validUntil",
        "supersedes",
        "sensitivity",
        "appliedRedaction",
        "content",
        "body",
        "payload",
        "contentHash",
        "v1Preserved",
    }
)


def _collect_v1_preserved(record: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(record.get("v1Preserved"), dict):
        return dict(record["v1Preserved"])
    preserved: dict[str, Any] = {}
    for key, value in record.items():
        if key in V1_KNOWN_SEMANTIC_KEYS or key in FINGERPRINT_EXCLUDED:
            continue
        preserved[key] = value
    return preserved or None


def _semantic_view_for_fingerprint(record: dict[str, Any]) -> dict[str, Any]:
    """Project v1 and v2 envelopes onto the same semantic shape for stable fingerprints."""
    stable_id = record.get("stableId") or record.get("id")
    project_id = record.get("projectId") or record.get("project")
    view: dict[str, Any] = {}
    if isinstance(stable_id, str) and stable_id.strip():
        view["stableId"] = stable_id.strip()
    if isinstance(project_id, str) and project_id.strip():
        view["projectId"] = project_id.strip()
    if isinstance(record.get("category"), str) and record["category"].strip():
        view["category"] = record["category"].strip()

    payload = _semantic_payload(record)
    if payload is not None:
        view["payload"] = payload

    for key in ("scope", "confidence", "observedAt", "lastValidatedAt"):
        if key in record and _include_optional_allowlist_field(record, key, record[key]):
            view[key] = record[key]

    preserved = _collect_v1_preserved(record)
    if preserved:
        view["v1Preserved"] = preserved

    return view


def _normalize_envelope_semantics(record: dict[str, Any]) -> dict[str, Any]:
    return _semantic_view_for_fingerprint(record)


def _normalize_interchange_note(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in INTERCHANGE_FIELD_ALLOWLIST:
        if key not in record:
            continue
        if key == "fields" and isinstance(record.get("fields"), dict):
            out["fields"] = {
                k: v
                for k, v in record["fields"].items()
                if k not in INTERCHANGE_FIELD_EXCLUDED
            }
        else:
            out[key] = record[key]
    return out


def fingerprint_payload(record: dict[str, Any]) -> dict[str, Any]:
    """Return the normalized semantic dict hashed by :func:`note_fingerprint`."""
    if not isinstance(record, dict):
        raise TypeError("record must be a dict")
    if record.get("schemaVersion") in (1, 2) or record.get("stableId") or (
        record.get("projectId") and record.get("category")
    ):
        return _normalize_envelope_semantics(record)
    if "body" in record and "category" in record:
        return _normalize_interchange_note(record)
    return _normalize_envelope_semantics(record)


def note_fingerprint(record: dict[str, Any]) -> str:
    """Stable SHA-256 over semantic content (allowlist-only, evolution fields excluded)."""
    body = fingerprint_payload(record)
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def fingerprints_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return note_fingerprint(left) == note_fingerprint(right)


def stable_id_of(record: dict[str, Any]) -> str:
    sid = record.get("stableId") or record.get("id")
    if not isinstance(sid, str) or not sid.strip():
        raise ValueError("record missing stable id")
    return sid.strip()


@dataclass(frozen=True)
class ImportOutcome:
    stable_id: str
    remapped: bool
    created: bool


def _remap_id(stable_id: str, existing_ids: set[str]) -> str:
    suffix = hashlib.sha256(stable_id.encode("utf-8")).hexdigest()[:8]
    candidate = f"{stable_id}-sw-{suffix}"
    counter = 1
    while candidate in existing_ids:
        candidate = f"{stable_id}-sw-{suffix}-{counter}"
        counter += 1
    return candidate


def import_record(
    store: dict[str, dict[str, Any]],
    raw: dict[str, Any],
    *,
    upgrade: bool = True,
) -> ImportOutcome:
    """Import a record into an in-memory store using fingerprint deduplication.

    When the stable id already exists and fingerprints match, the import is a
    no-op (no remap, no new record). When ids collide but semantics differ, the
    incoming record is remapped. When upgrade is True, v1 records are upgraded
    to v2 before persistence.
    """
    working = dict(raw)
    if upgrade:
        try:
            working = upgrade_if_needed(working)
        except Exception:
            pass

    stable_id = stable_id_of(working)
    incoming_fp = note_fingerprint(raw)

    if stable_id in store:
        if note_fingerprint(store[stable_id]) == incoming_fp:
            return ImportOutcome(stable_id, remapped=False, created=False)
        new_id = _remap_id(stable_id, set(store))
        store[new_id] = working
        return ImportOutcome(new_id, remapped=True, created=True)

    for existing_id, existing in store.items():
        if note_fingerprint(existing) == incoming_fp:
            return ImportOutcome(existing_id, remapped=False, created=False)

    store[stable_id] = working
    return ImportOutcome(stable_id, remapped=False, created=True)
