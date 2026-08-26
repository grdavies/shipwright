#!/usr/bin/env python3
"""TriageEvidence@v1 contracts — digest-bound freshness and redacted persistence (PRD 332 R2, R3, R6, R10, R13)."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from exploration_security import assert_secret_free as _assert_secret_free
from gate_evidence import utc_now

EVIDENCE_VERSION = "TriageEvidence@v1"
PRODUCER_CONTRACT_VERSION = "TriageEvidence@v1"

SIGNAL_STATE_PRESENT = "present"
SIGNAL_STATE_ABSENT = "absent"
SAFETY_CLASS_ADVISORY = "advisory"
SAFETY_CLASS_SAFETY_FLOOR = "safety-floor"

VALID_SIGNAL_STATES = frozenset({SIGNAL_STATE_PRESENT, SIGNAL_STATE_ABSENT})
VALID_SAFETY_CLASSES = frozenset({SAFETY_CLASS_ADVISORY, SAFETY_CLASS_SAFETY_FLOOR})
INVALIDATION_VALID = "valid"
INVALIDATION_INVALIDATED = "invalidated"

SHA256_HEX = re.compile(r"^[0-9a-f]{64}$")
SHA256_PREFIX = re.compile(r"^sha256:[0-9a-f]{64}$")

WEIGHT_MIN = 0.0
WEIGHT_MAX = 1.0


class TriageEvidenceError(ValueError):
    """Invalid or stale triage evidence."""


class TriageEvidenceSecretError(TriageEvidenceError):
    """Secret-bearing evidence refused before persistence."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _parse_iso8601(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _normalize_digest(value: str) -> str:
    text = (value or "").strip()
    if SHA256_PREFIX.fullmatch(text):
        return text.split(":", 1)[1]
    if SHA256_HEX.fullmatch(text):
        return text
    return ""


def compute_payload_digest(material: Mapping[str, Any]) -> str:
    """Digest over signal payload bytes — excludes envelope timestamps (R13)."""
    body = {k: v for k, v in material.items() if k not in ("freshness", "explain")}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def compute_producer_signature(producer_path: str) -> str:
    material = f"{producer_path.strip()}:{PRODUCER_CONTRACT_VERSION}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def build_freshness_envelope(
    *,
    payload_digest: str,
    observed_at: str | None = None,
    producer_path: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    digest_hex = _normalize_digest(payload_digest)
    if not digest_hex:
        raise TriageEvidenceError("freshness-digest-required")
    signature = compute_producer_signature(producer_path)
    envelope: dict[str, Any] = {
        "digest": f"sha256:{digest_hex}",
        "observedAt": observed_at or utc_now(),
        "producerPath": producer_path.strip(),
        "producerSignature": f"sha256:{signature}",
        "invalidation": {"state": INVALIDATION_VALID},
    }
    if expires_at:
        envelope["expiresAt"] = expires_at
    return envelope


def build_signal(
    signal_id: str,
    *,
    weight: float,
    safety_class: str = SAFETY_CLASS_ADVISORY,
    state: str = SIGNAL_STATE_PRESENT,
    value: float | None = None,
    absent_reason: str | None = None,
    producer_path: str = "scripts/triage_evidence.py",
    observed_at: str | None = None,
    expires_at: str | None = None,
    payload_extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Construct one versioned signal entry with digest-bound freshness."""
    normalized_id = signal_id.strip()
    if not normalized_id:
        raise TriageEvidenceError("signal-id-required")
    if state not in VALID_SIGNAL_STATES:
        raise TriageEvidenceError("invalid-signal-state")
    if safety_class not in VALID_SAFETY_CLASSES:
        raise TriageEvidenceError("invalid-safety-class")
    if not WEIGHT_MIN <= weight <= WEIGHT_MAX:
        raise TriageEvidenceError("invalid-weight")

    signal: dict[str, Any] = {
        "id": normalized_id,
        "weight": weight,
        "safetyClass": safety_class,
        "state": state,
    }
    if state == SIGNAL_STATE_ABSENT:
        signal["absentReason"] = (absent_reason or "producer-unavailable").strip()
    else:
        if value is None:
            raise TriageEvidenceError("present-signal-requires-value")
        signal["value"] = float(value)

    if payload_extra:
        signal.update(dict(payload_extra))

    if state == SIGNAL_STATE_ABSENT and "value" in signal:
        raise TriageEvidenceError("absent-signal-cannot-carry-value")

    payload_digest = compute_payload_digest(signal)
    signal["freshness"] = build_freshness_envelope(
        payload_digest=payload_digest,
        observed_at=observed_at,
        producer_path=producer_path,
        expires_at=expires_at,
    )
    return signal


def build_explain(signals: list[Mapping[str, Any]], *, computed_at: str | None = None) -> dict[str, Any]:
    """Deterministic explain payload for operator surfaces (R10)."""
    components: list[dict[str, Any]] = []
    for signal in sorted(signals, key=lambda item: str(item.get("id") or "")):
        disposition = signal_disposition(signal)
        entry: dict[str, Any] = {
            "id": signal.get("id"),
            "weight": signal.get("weight"),
            "safetyClass": signal.get("safetyClass"),
            "state": signal.get("state"),
            "disposition": disposition,
        }
        if signal.get("state") == SIGNAL_STATE_ABSENT:
            entry["absentReason"] = signal.get("absentReason")
        elif disposition == "fresh" and "value" in signal:
            entry["value"] = signal.get("value")
        components.append(entry)
    return {
        "version": EVIDENCE_VERSION,
        "computedAt": computed_at or utc_now(),
        "components": components,
    }


def build_triage_evidence(signals: list[dict[str, Any]], *, computed_at: str | None = None) -> dict[str, Any]:
    normalized = [parse_signal_entry(item) for item in signals]
    explain = build_explain(normalized, computed_at=computed_at)
    document: dict[str, Any] = {
        "version": EVIDENCE_VERSION,
        "signals": normalized,
        "explain": explain,
    }
    validate_triage_evidence(document)
    return document


def parse_signal_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise TriageEvidenceError("signal-must-be-object")
    signal = deepcopy(dict(entry))
    validate_signal_entry(signal)
    return signal


def validate_signal_entry(signal: Mapping[str, Any]) -> None:
    version_hint = str(signal.get("version") or EVIDENCE_VERSION)
    if version_hint != EVIDENCE_VERSION and "id" in signal:
        pass  # signal entries are not versioned independently

    signal_id = str(signal.get("id") or "").strip()
    if not signal_id:
        raise TriageEvidenceError("signal-id-required")

    state = str(signal.get("state") or "").strip()
    if state not in VALID_SIGNAL_STATES:
        raise TriageEvidenceError("invalid-signal-state")

    safety_class = str(signal.get("safetyClass") or SAFETY_CLASS_ADVISORY).strip()
    if safety_class not in VALID_SAFETY_CLASSES:
        raise TriageEvidenceError("invalid-safety-class")

    weight = signal.get("weight")
    if not isinstance(weight, (int, float)) or not WEIGHT_MIN <= float(weight) <= WEIGHT_MAX:
        raise TriageEvidenceError("invalid-weight")

    if state == SIGNAL_STATE_ABSENT:
        if "value" in signal:
            raise TriageEvidenceError("absent-signal-cannot-carry-value")
        reason = str(signal.get("absentReason") or "").strip()
        if not reason:
            raise TriageEvidenceError("absent-reason-required")
    else:
        value = signal.get("value")
        if not isinstance(value, (int, float)):
            raise TriageEvidenceError("present-signal-requires-value")

    freshness = signal.get("freshness")
    if not isinstance(freshness, dict):
        raise TriageEvidenceError("freshness-envelope-required")
    validate_freshness_envelope(freshness, compute_payload_digest(signal))


def validate_freshness_envelope(
    envelope: Mapping[str, Any],
    expected_payload_digest: str,
    *,
    now: datetime | None = None,
) -> None:
    """Reject clock-only freshness and bind digest to payload (R3, R13)."""
    digest = _normalize_digest(str(envelope.get("digest") or ""))
    if not digest:
        raise TriageEvidenceError("clock-only-freshness-rejected")

    observed_at = str(envelope.get("observedAt") or "").strip()
    if not observed_at:
        raise TriageEvidenceError("observed-at-required")

    producer_path = str(envelope.get("producerPath") or "").strip()
    if not producer_path:
        raise TriageEvidenceError("producer-path-required")

    producer_signature = _normalize_digest(str(envelope.get("producerSignature") or ""))
    if not producer_signature:
        raise TriageEvidenceError("producer-signature-required")
    expected_signature = compute_producer_signature(producer_path)
    if producer_signature != expected_signature:
        raise TriageEvidenceError("producer-signature-mismatch")

    expected_digest = _normalize_digest(expected_payload_digest)
    if digest != expected_digest:
        raise TriageEvidenceError("digest-mismatch")

    invalidation = envelope.get("invalidation")
    if not isinstance(invalidation, dict):
        raise TriageEvidenceError("invalidation-metadata-required")
    state = str(invalidation.get("state") or "").strip()
    if state not in {INVALIDATION_VALID, INVALIDATION_INVALIDATED}:
        raise TriageEvidenceError("invalid-invalidation-state")

    if state == INVALIDATION_INVALIDATED:
        raise TriageEvidenceError("evidence-invalidated")

    expires_at = envelope.get("expiresAt")
    if expires_at is not None:
        expiry = _parse_iso8601(str(expires_at))
        current = now or datetime.now(timezone.utc)
        if expiry is None:
            raise TriageEvidenceError("invalid-expires-at")
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if current >= expiry:
            raise TriageEvidenceError("evidence-expired")


def validate_triage_evidence(document: Mapping[str, Any]) -> None:
    if str(document.get("version") or "") != EVIDENCE_VERSION:
        raise TriageEvidenceError("invalid-version")
    signals = document.get("signals")
    if not isinstance(signals, list):
        raise TriageEvidenceError("signals-array-required")
    parsed: list[dict[str, Any]] = []
    for index, entry in enumerate(signals):
        if not isinstance(entry, Mapping):
            raise TriageEvidenceError(f"signal[{index}]-must-be-object")
        parsed.append(parse_signal_entry(entry))

    explain = document.get("explain")
    if not isinstance(explain, dict):
        raise TriageEvidenceError("explain-required")
    expected_explain = build_explain(parsed)
    if canonical_json(explain.get("components") or []) != canonical_json(expected_explain["components"]):
        raise TriageEvidenceError("explain-mismatch")


def parse_triage_evidence(document: Mapping[str, Any]) -> dict[str, Any]:
    """Parse and validate a TriageEvidence@v1 document."""
    parsed = deepcopy(dict(document))
    validate_triage_evidence(parsed)
    assert_secret_free(parsed)
    return parsed


def serialize_triage_evidence(document: Mapping[str, Any]) -> str:
    """Canonical serialization for stable roundtrips (R2, R10)."""
    parsed = parse_triage_evidence(document)
    return canonical_json(parsed)


def signal_disposition(signal: Mapping[str, Any], *, now: datetime | None = None) -> str:
    if str(signal.get("state") or "") == SIGNAL_STATE_ABSENT:
        return "absent"
    freshness = signal.get("freshness")
    if not isinstance(freshness, dict):
        return "invalid"
    invalidation = freshness.get("invalidation")
    if isinstance(invalidation, dict) and invalidation.get("state") == INVALIDATION_INVALIDATED:
        return "invalidated"
    try:
        validate_freshness_envelope(freshness, compute_payload_digest(signal), now=now)
    except TriageEvidenceError as exc:
        cause = str(exc)
        if cause == "evidence-expired":
            return "stale"
        if cause in {"digest-mismatch", "evidence-invalidated", "producer-signature-mismatch"}:
            return "invalidated"
        return "invalid"
    return "fresh"


def safety_floor_precedence(
    safety_signal: Mapping[str, Any],
    advisory_signal: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> str:
    """Fresh safety-floor inputs outrank stale advisory signals (R3, R6)."""
    safety_disposition = signal_disposition(safety_signal, now=now)
    advisory_disposition = signal_disposition(advisory_signal, now=now)
    if safety_disposition == "fresh":
        return "safety-floor"
    if advisory_disposition == "fresh":
        return "advisory"
    if safety_disposition in {"stale", "invalidated", "invalid"}:
        return "safety-floor-stale"
    return advisory_disposition


def invalidate_signal(signal: dict[str, Any], *, reason: str, invalidated_at: str | None = None) -> dict[str, Any]:
    updated = deepcopy(signal)
    freshness = updated.get("freshness")
    if not isinstance(freshness, dict):
        raise TriageEvidenceError("freshness-envelope-required")
    freshness["invalidation"] = {
        "state": INVALIDATION_INVALIDATED,
        "reason": reason.strip(),
        "invalidatedAt": invalidated_at or utc_now(),
    }
    updated["freshness"] = freshness
    return updated


def assert_secret_free(document: Mapping[str, Any]) -> None:
    try:
        _assert_secret_free(document)
    except Exception as exc:  # noqa: BLE001 — map exploration boundary
        raise TriageEvidenceSecretError(str(exc)) from exc


def write_triage_evidence(path: Path, document: Mapping[str, Any]) -> Path:
    """Persist evidence after secret refusal and schema validation (R6, R13)."""
    parsed = parse_triage_evidence(document)
    assert_secret_free(parsed)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_triage_evidence(parsed) + "\n", encoding="utf-8")
    return path


def read_triage_evidence(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    document = json.loads(raw)
    return parse_triage_evidence(document)
