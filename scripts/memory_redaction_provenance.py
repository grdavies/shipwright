#!/usr/bin/env python3
"""Applied-redaction provenance and memory egress enforcement (PRD 082 R29, R32).

Envelope ``appliedRedaction`` records the destination tier applied, pattern-set version,
and substitution count — distinct from ``sensitivity``. Missing provenance fails closed at
egress; stricter destinations re-redact or refuse with a durable refusal entry.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from memory_redact import DESTINATION_VALUES, redact
from secret_patterns import DENY_PATTERNS, REDACTIONS

EgressPoint = Literal["memory-sync", "cross-project-copy"]

EGRESS_ENFORCEMENT_POINTS: frozenset[str] = frozenset({"memory-sync", "cross-project-copy"})

DESTINATION_TIER_ORDER: tuple[str, ...] = (
    "local",
    "logs",
    "committed",
    "external",
    "cross-project",
)
DESTINATION_TIER_RANK: dict[str, int] = {
    tier: index for index, tier in enumerate(DESTINATION_TIER_ORDER)
}

DEFAULT_DESTINATION_POLICY_ID = "shipwright.memory.redaction"
DEFAULT_DESTINATION_POLICY_VERSION = "1"
REDACTION_SCRIPT = "scripts/memory-redact.py"

EGRESS_REFUSAL_JOURNAL_DIR = Path(".cursor") / "sw-memory-egress-refusal-journal"
EGRESS_REFUSAL_JOURNAL_SCHEMA_VERSION = 1


class ProvenanceError(ValueError):
    """Redaction provenance or egress enforcement failure."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def pattern_set_version() -> str:
    """Stable version token for the active deny-pattern corpus."""
    names = sorted(p.name for p in DENY_PATTERNS)
    digest = hashlib.sha256(",".join(names).encode("utf-8")).hexdigest()[:16]
    return f"deny-patterns:{len(names)}:{digest}"


def resolve_destination_tier(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProvenanceError("destination-tier:missing")
    normalized = value.strip()
    if normalized not in DESTINATION_VALUES:
        raise ProvenanceError(f"destination-tier:invalid:{normalized}")
    return normalized


def destination_tier_rank(tier: str) -> int:
    resolved = resolve_destination_tier(tier)
    return DESTINATION_TIER_RANK[resolved]


def is_stricter_destination(recorded_tier: Any, target_tier: Any) -> bool:
    recorded = resolve_destination_tier(recorded_tier)
    target = resolve_destination_tier(target_tier)
    return destination_tier_rank(target) > destination_tier_rank(recorded)


def count_substitutions(text: str, *, destination: str) -> int:
    resolve_destination_tier(destination)
    total = 0
    out = text
    for pattern, replacement in REDACTIONS:
        out, count = pattern.subn(replacement, out)
        total += count
    return total


def provenance_is_complete(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    if record.get("applied") is not True:
        return False
    for field in ("destinationTierApplied", "patternSetVersion", "substitutionCount"):
        if field not in record:
            return False
    try:
        resolve_destination_tier(record.get("destinationTierApplied"))
    except ProvenanceError:
        return False
    version = record.get("patternSetVersion")
    if not isinstance(version, str) or not version.strip():
        return False
    count = record.get("substitutionCount")
    if not isinstance(count, int) or count < 0:
        return False
    return True


def treat_as_unredacted(record: Any) -> bool:
    """True when provenance is absent — payload must be treated as unredacted."""
    return not provenance_is_complete(record)


def build_applied_redaction_record(
    *,
    destination_tier: str,
    text: str,
    applied: bool = True,
    profile: str | None = None,
    redacted_at: str | None = None,
) -> dict[str, Any]:
    tier = resolve_destination_tier(destination_tier)
    return {
        "applied": applied,
        "destinationTierApplied": tier,
        "patternSetVersion": pattern_set_version(),
        "substitutionCount": count_substitutions(text, destination=tier),
        "profile": profile,
        "redactedAt": redacted_at or utc_now_iso(),
        "redactionScript": REDACTION_SCRIPT,
    }


def redact_with_provenance(text: str, *, destination_tier: str) -> tuple[str, dict[str, Any]]:
    tier = resolve_destination_tier(destination_tier)
    redacted = redact(text, destination=tier)
    record = build_applied_redaction_record(destination_tier=tier, text=text)
    return redacted, record


def _journal_path(root: Path, scope: str = "default") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (scope or "default").strip()) or "default"
    return root / EGRESS_REFUSAL_JOURNAL_DIR / f"{safe}.json"


def empty_egress_refusal_journal(*, scope: str = "default") -> dict[str, Any]:
    return {
        "schemaVersion": EGRESS_REFUSAL_JOURNAL_SCHEMA_VERSION,
        "scope": scope,
        "entries": [],
        "updatedAt": utc_now_iso(),
    }


def load_egress_refusal_journal(root: Path, *, scope: str = "default") -> dict[str, Any]:
    path = _journal_path(root, scope)
    if not path.is_file():
        return empty_egress_refusal_journal(scope=scope)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_egress_refusal_journal(scope=scope)
    if not isinstance(doc, dict):
        return empty_egress_refusal_journal(scope=scope)
    doc.setdefault("schemaVersion", EGRESS_REFUSAL_JOURNAL_SCHEMA_VERSION)
    doc.setdefault("scope", scope)
    doc.setdefault("entries", [])
    return doc


def save_egress_refusal_journal(root: Path, journal: dict[str, Any], *, scope: str = "default") -> Path:
    path = _journal_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(journal)
    payload["scope"] = scope
    payload["updatedAt"] = utc_now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _entry_digest(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_egress_refusal(
    root: Path,
    *,
    stable_id: str,
    egress_point: str,
    destination_tier: str,
    destination_policy_id: str,
    destination_policy_version: str,
    cause: str,
    scope: str = "default",
) -> dict[str, Any]:
    if egress_point not in EGRESS_ENFORCEMENT_POINTS:
        raise ProvenanceError(f"egress-point:invalid:{egress_point}")
    journal = load_egress_refusal_journal(root, scope=scope)
    entry: dict[str, Any] = {
        "stableId": stable_id.strip(),
        "egressPoint": egress_point,
        "destinationTier": resolve_destination_tier(destination_tier),
        "destinationPolicyId": destination_policy_id.strip(),
        "destinationPolicyVersion": str(destination_policy_version).strip(),
        "cause": cause,
        "refusedAt": utc_now_iso(),
    }
    entry["digest"] = _entry_digest(entry)
    entries = list(journal.get("entries") or [])
    entries.append(entry)
    journal["entries"] = entries
    path = save_egress_refusal_journal(root, journal, scope=scope)
    return {"verdict": "recorded", "journalPath": str(path), "entry": entry}


def enforce_egress(
    envelope: dict[str, Any],
    *,
    egress_point: str,
    destination_tier: str,
    destination_policy_id: str = DEFAULT_DESTINATION_POLICY_ID,
    destination_policy_version: str = DEFAULT_DESTINATION_POLICY_VERSION,
    payload_text: str | None = None,
    root: Path | None = None,
    scope: str = "default",
    allow_reredact: bool = True,
) -> dict[str, Any]:
    """Validate or re-apply redaction before memory egress."""
    if egress_point not in EGRESS_ENFORCEMENT_POINTS:
        return {"verdict": "fail", "cause": f"egress:invalid-point:{egress_point}"}

    stable_id = str(envelope.get("stableId") or "").strip()
    provenance = envelope.get("appliedRedaction")

    if treat_as_unredacted(provenance):
        refusal = None
        if root is not None and stable_id:
            refusal = record_egress_refusal(
                root,
                stable_id=stable_id,
                egress_point=egress_point,
                destination_tier=destination_tier,
                destination_policy_id=destination_policy_id,
                destination_policy_version=destination_policy_version,
                cause="egress:missing-redaction-provenance",
                scope=scope,
            )
        return {
            "verdict": "fail",
            "cause": "egress:missing-redaction-provenance",
            "treatedAsUnredacted": True,
            "refusal": refusal,
        }

    recorded_tier = str(provenance.get("destinationTierApplied"))
    target_tier = resolve_destination_tier(destination_tier)

    if not is_stricter_destination(recorded_tier, target_tier):
        return {
            "verdict": "pass",
            "action": "allow",
            "destinationTierApplied": recorded_tier,
            "destinationPolicyId": destination_policy_id,
            "destinationPolicyVersion": destination_policy_version,
        }

    if allow_reredact and payload_text is not None:
        redacted, new_provenance = redact_with_provenance(payload_text, destination_tier=target_tier)
        updated = dict(envelope)
        updated["appliedRedaction"] = new_provenance
        return {
            "verdict": "pass",
            "action": "re-redacted",
            "destinationTierApplied": target_tier,
            "destinationPolicyId": destination_policy_id,
            "destinationPolicyVersion": destination_policy_version,
            "envelope": updated,
            "payloadText": redacted,
            "fromTier": recorded_tier,
        }

    refusal = None
    if root is not None and stable_id:
        refusal = record_egress_refusal(
            root,
            stable_id=stable_id,
            egress_point=egress_point,
            destination_tier=target_tier,
            destination_policy_id=destination_policy_id,
            destination_policy_version=destination_policy_version,
            cause="egress:stricter-destination-refused",
            scope=scope,
        )
    return {
        "verdict": "fail",
        "cause": "egress:stricter-destination-refused",
        "fromTier": recorded_tier,
        "toTier": target_tier,
        "destinationPolicyId": destination_policy_id,
        "destinationPolicyVersion": destination_policy_version,
        "refusal": refusal,
    }
