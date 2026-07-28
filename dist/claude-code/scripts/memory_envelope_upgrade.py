#!/usr/bin/env python3
"""v1 memory envelope reader, v2 upgrader, and stable-id alias merge ledger (PRD 082 R29)."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from memory_envelope_v2 import (
    SCHEMA_VERSION,
    V1_SCHEMA_VERSION,
    EnvelopeError,
    compute_content_hash,
    empty_applied_redaction,
    empty_scope,
    new_envelope,
    parse_envelope,
)

ALIAS_LEDGER_DIR = Path(".cursor") / "sw-memory-envelope-aliases"
ALIAS_LEDGER_SCHEMA_VERSION = 1

V1_KNOWN_FIELDS = frozenset(
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
    }
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def is_v1_envelope(doc: Any) -> bool:
    if not isinstance(doc, dict):
        return False
    version = doc.get("schemaVersion")
    if version is None:
        return bool(doc.get("id") or doc.get("stableId"))
    return version == V1_SCHEMA_VERSION


def read_v1(doc: Any) -> dict[str, Any]:
    """Parse a v1 envelope without upgrading."""
    if not isinstance(doc, dict):
        raise EnvelopeError("v1:not-object")
    if not is_v1_envelope(doc):
        raise EnvelopeError("v1:not-v1")
    return dict(doc)


def _split_v1_fields(doc: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    known: dict[str, Any] = {}
    preserved: dict[str, Any] = {}
    for key, value in doc.items():
        if key in V1_KNOWN_FIELDS:
            known[key] = value
        else:
            preserved[key] = value
    return known, preserved


def upgrade_v1_to_v2(doc: Any) -> dict[str, Any]:
    """Upgrade a v1 record to v2, preserving unknown fields under v1Preserved."""
    v1 = read_v1(doc)
    known, preserved = _split_v1_fields(v1)

    stable_id = str(known.get("stableId") or known.get("id") or "").strip()
    if not stable_id:
        raise EnvelopeError("v1:missing-stable-id")

    project_id = str(known.get("projectId") or known.get("project") or "default").strip() or "default"
    category = str(known.get("category") or "learning").strip() or "learning"
    status = known.get("status") or "active"
    if status not in ("active", "superseded"):
        status = "active"

    scope = known.get("scope")
    if not isinstance(scope, dict):
        scope = empty_scope()

    evidence = known.get("evidenceRefs")
    if evidence is None:
        legacy_evidence = known.get("evidence")
        evidence = legacy_evidence if isinstance(legacy_evidence, list) else []
    evidence_refs = [str(x) for x in evidence if isinstance(x, str)]

    confidence = known.get("confidence", 0.5)
    if not isinstance(confidence, (int, float)):
        confidence = 0.5

    sensitivity = known.get("sensitivity") or "internal"
    if sensitivity not in ("public", "internal", "private", "secret"):
        sensitivity = "internal"

    applied = known.get("appliedRedaction")
    if not isinstance(applied, dict):
        applied = empty_applied_redaction()

    supersedes = known.get("supersedes") or []
    if not isinstance(supersedes, list):
        supersedes = []
    supersedes_list = [str(x) for x in supersedes if isinstance(x, str)]

    payload: dict[str, Any] | None = None
    if isinstance(known.get("payload"), dict):
        payload = dict(known["payload"])
    elif known.get("content") is not None:
        payload = {"content": known.get("content")}
    elif known.get("body") is not None:
        payload = {"body": known.get("body")}

    envelope = new_envelope(
        stable_id=stable_id,
        project_id=project_id,
        category=category,
        status=status,  # type: ignore[arg-type]
        scope=scope,
        evidence_refs=evidence_refs,
        confidence=float(confidence),
        observed_at=known.get("observedAt") or _utc_now_iso(),
        last_validated_at=known.get("lastValidatedAt"),
        valid_until=known.get("validUntil"),
        supersedes=supersedes_list,
        sensitivity=sensitivity,  # type: ignore[arg-type]
        applied_redaction=applied,
        payload=payload,
    )
    if preserved:
        envelope["v1Preserved"] = preserved
        envelope["contentHash"] = compute_content_hash(envelope)
    return envelope


def upgrade_if_needed(doc: Any) -> dict[str, Any]:
    if isinstance(doc, dict) and doc.get("schemaVersion") == SCHEMA_VERSION:
        return parse_envelope(doc)
    if is_v1_envelope(doc):
        return upgrade_v1_to_v2(doc)
    raise EnvelopeError("upgrade:unsupported-version")


def alias_ledger_path(root: Path, scope: str = "default") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (scope or "default").strip()) or "default"
    return root / ALIAS_LEDGER_DIR / f"{safe}.json"


def empty_alias_ledger(*, scope: str = "default") -> dict[str, Any]:
    return {
        "schemaVersion": ALIAS_LEDGER_SCHEMA_VERSION,
        "scope": scope,
        "aliases": {},
        "merges": [],
        "updatedAt": _utc_now_iso(),
    }


def load_alias_ledger(root: Path, *, scope: str = "default") -> dict[str, Any]:
    path = alias_ledger_path(root, scope)
    if not path.is_file():
        return empty_alias_ledger(scope=scope)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_alias_ledger(scope=scope)
    if not isinstance(doc, dict):
        return empty_alias_ledger(scope=scope)
    doc.setdefault("schemaVersion", ALIAS_LEDGER_SCHEMA_VERSION)
    doc.setdefault("scope", scope)
    doc.setdefault("aliases", {})
    doc.setdefault("merges", [])
    return doc


def save_alias_ledger(root: Path, ledger: dict[str, Any], *, scope: str = "default") -> Path:
    path = alias_ledger_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(ledger)
    payload["scope"] = scope
    payload["updatedAt"] = _utc_now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def record_alias(
    ledger: dict[str, Any],
    *,
    from_id: str,
    to_id: str,
    reason: str = "merge",
) -> dict[str, Any]:
    """Record a stable-id alias mapping (from_id redirects to canonical to_id)."""
    src = from_id.strip()
    dst = to_id.strip()
    if not src or not dst:
        raise EnvelopeError("alias:empty-id")
    if src == dst:
        raise EnvelopeError("alias:self-map")
    aliases = dict(ledger.get("aliases") or {})
    aliases[src] = dst
    merges = list(ledger.get("merges") or [])
    merges.append(
        {
            "fromId": src,
            "toId": dst,
            "reason": reason,
            "at": _utc_now_iso(),
        }
    )
    out = dict(ledger)
    out["aliases"] = aliases
    out["merges"] = merges
    return out


def resolve_stable_id(ledger: dict[str, Any], stable_id: str, *, max_hops: int = 32) -> str:
    aliases: dict[str, str] = dict(ledger.get("aliases") or {})
    current = stable_id.strip()
    for _ in range(max_hops):
        nxt = aliases.get(current)
        if not nxt or nxt == current:
            return current
        current = nxt
    raise EnvelopeError("alias:max-hops")
