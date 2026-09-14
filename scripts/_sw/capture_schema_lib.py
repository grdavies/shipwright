"""Hand-rolled capture-event schema validation and privacy scan (PRD 350 R3, R5, SC1, SC5).

Stdlib only — no third-party JSON Schema engines (TR3).
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "1"
EVENT_ID_HEX_LEN = 16

EVENT_TYPES = frozenset(
    {
        "task_start",
        "milestone",
        "discovery",
        "verification",
        "blocker",
        "delegation",
        "interruption",
    }
)

PROVENANCE_KINDS = frozenset(
    {
        "tool_output",
        "test_result",
        "human_statement",
        "inferred",
        "sub_agent_feed",
    }
)

VERIFICATION_OUTCOMES = frozenset({"pass", "fail", "partial"})

REQUIRED_FIELDS = (
    "eventId",
    "schemaVersion",
    "eventType",
    "runId",
    "phaseId",
    "agentId",
    "timestamp",
    "provenanceKind",
    "provenanceRef",
    "summary",
    "pendingState",
)

OPTIONAL_STRING_FIELDS = (
    "gapRef",
    "memoryObservationRef",
    "delegationTarget",
    "blockerCondition",
    "verificationEvidence",
    "resumedFromEventId",
    "dedupSalt",
)

MAX_SUMMARY_LENGTH = 500
MAX_VERIFICATION_EVIDENCE_LENGTH = 500
PRIVACY_LINE_LIMIT = 200

# Lines longer than PRIVACY_LINE_LIMIT must start with one of these prefixes (SC1).
KNOWN_STRUCTURED_PREFIXES: tuple[str, ...] = (
    "{",
    "[",
    "sw:",
    "eventId=",
    "eventId:",
    "ref:",
    "path:",
    "id:",
    "check:",
    "tool:",
    "status:",
    "sha:",
    "runId=",
    "phaseId=",
    "http://",
    "https://",
)

_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-+=/]{8,}", re.IGNORECASE)
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"
)
# Long base64-looking tokens (SC5). Pure hex (git SHA / digests) excluded in _privacy_scan.
_BASE64_RE = re.compile(
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])"
)
_PURE_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class CaptureSchemaError(ValueError):
    """Raised when a capture event fails schema validation."""


class CapturePrivacyError(ValueError):
    """Raised when a capture event fails the privacy / credential scan."""


def schema_path() -> Path:
    return Path(__file__).resolve().parent / "capture-event-schema.json"


def load_schema() -> dict[str, Any]:
    return json.loads(schema_path().read_text(encoding="utf-8"))


def compute_event_id(
    run_id: str,
    phase_id: str,
    event_type: str,
    timestamp: str,
    *,
    dedup_salt: str = "",
) -> str:
    """Deterministic 16-char hex event id (R3, TR4; PRD 352 R10/TR3).

    ``dedup_salt`` carries a microsecond/monotonic (or stable milestone) component
    so two same-second events can receive distinct ids. When ``dedup_salt`` is
    non-empty, identity is ``runId:phaseId:eventType:dedup_salt`` (timestamp
    excluded) so callers can pair wall-clock timestamps with stable dedup keys
    (PRD 352 R11). When empty, identity includes ``timestamp`` for compatibility.
    """
    if dedup_salt:
        material = f"{run_id}:{phase_id}:{event_type}:{dedup_salt}".encode("utf-8")
    else:
        material = f"{run_id}:{phase_id}:{event_type}:{timestamp}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:EVENT_ID_HEX_LEN]


def _as_text_blobs(event: Mapping[str, Any]) -> list[str]:
    blobs: list[str] = []
    for key, value in event.items():
        if isinstance(value, str):
            blobs.append(value)
        elif isinstance(value, dict):
            blobs.append(json.dumps(value, ensure_ascii=False, sort_keys=True))
        elif isinstance(value, list):
            blobs.append(json.dumps(value, ensure_ascii=False))
        else:
            continue
        _ = key
    return blobs


def _privacy_scan(event: Mapping[str, Any]) -> None:
    for blob in _as_text_blobs(event):
        for line in blob.splitlines() or [blob]:
            stripped = line.strip()
            if len(stripped) > PRIVACY_LINE_LIMIT and not stripped.startswith(
                KNOWN_STRUCTURED_PREFIXES
            ):
                raise CapturePrivacyError(
                    "raw transcript pattern: line exceeds 200 chars without structured prefix"
                )
            if _BEARER_RE.search(line):
                raise CapturePrivacyError("credential pattern: Bearer token")
            if _PRIVATE_KEY_RE.search(line):
                raise CapturePrivacyError("credential pattern: private key header")
            for match in _BASE64_RE.finditer(line):
                token = match.group(0).rstrip("=")
                # Git SHAs / content digests are pure hex — allow them.
                if _PURE_HEX_RE.fullmatch(token):
                    continue
                raise CapturePrivacyError("credential pattern: base64 string > 40 chars")


def _require_str(event: Mapping[str, Any], field: str, *, allow_empty: bool = False) -> str:
    if field not in event:
        raise CaptureSchemaError(f"missing required field: {field}")
    value = event[field]
    if not isinstance(value, str):
        raise CaptureSchemaError(f"{field} must be a string")
    if not allow_empty and not value.strip():
        raise CaptureSchemaError(f"{field} must be non-empty")
    return value


def validate_event(event: dict[str, Any] | Mapping[str, Any]) -> None:
    """Validate capture event fields and run privacy scan. Raises on failure."""
    if not isinstance(event, Mapping):
        raise CaptureSchemaError("event must be an object")

    for field in REQUIRED_FIELDS:
        if field not in event:
            raise CaptureSchemaError(f"missing required field: {field}")

    schema_version = _require_str(event, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise CaptureSchemaError(f"schemaVersion must be {SCHEMA_VERSION!r}")

    event_type = _require_str(event, "eventType")
    if event_type not in EVENT_TYPES:
        raise CaptureSchemaError(f"invalid eventType: {event_type!r}")

    run_id = _require_str(event, "runId")
    phase_id = _require_str(event, "phaseId")
    _require_str(event, "agentId")
    timestamp = _require_str(event, "timestamp")
    if not _ISO8601_RE.match(timestamp):
        raise CaptureSchemaError(f"timestamp must be ISO-8601: {timestamp!r}")

    provenance_kind = _require_str(event, "provenanceKind")
    if provenance_kind not in PROVENANCE_KINDS:
        raise CaptureSchemaError(f"invalid provenanceKind: {provenance_kind!r}")
    _require_str(event, "provenanceRef")

    summary = _require_str(event, "summary")
    if len(summary) > MAX_SUMMARY_LENGTH:
        raise CaptureSchemaError(f"summary exceeds {MAX_SUMMARY_LENGTH} characters")

    pending = event.get("pendingState")
    if pending is not None and not isinstance(pending, dict):
        raise CaptureSchemaError("pendingState must be an object or null")

    event_id = _require_str(event, "eventId")
    if len(event_id) != EVENT_ID_HEX_LEN or any(c not in "0123456789abcdef" for c in event_id):
        raise CaptureSchemaError("eventId must be 16 lowercase hex characters")
    dedup_salt = ""
    if "dedupSalt" in event and event["dedupSalt"] is not None:
        if not isinstance(event["dedupSalt"], str):
            raise CaptureSchemaError("dedupSalt must be a string when present")
        dedup_salt = event["dedupSalt"]
    expected = compute_event_id(
        run_id, phase_id, event_type, timestamp, dedup_salt=dedup_salt
    )
    if event_id != expected:
        raise CaptureSchemaError(
            f"eventId mismatch: got {event_id!r}, expected {expected!r}"
        )

    for field in OPTIONAL_STRING_FIELDS:
        if field not in event or event[field] is None:
            continue
        value = event[field]
        if not isinstance(value, str):
            raise CaptureSchemaError(f"{field} must be a string when present")

    if "verificationOutcome" in event and event["verificationOutcome"] is not None:
        outcome = event["verificationOutcome"]
        if outcome not in VERIFICATION_OUTCOMES:
            raise CaptureSchemaError(f"invalid verificationOutcome: {outcome!r}")

    if "verificationEvidence" in event and event["verificationEvidence"] is not None:
        evidence = event["verificationEvidence"]
        if not isinstance(evidence, str):
            raise CaptureSchemaError("verificationEvidence must be a string")
        if len(evidence) > MAX_VERIFICATION_EVIDENCE_LENGTH:
            raise CaptureSchemaError(
                f"verificationEvidence exceeds {MAX_VERIFICATION_EVIDENCE_LENGTH} characters"
            )

    if "resumedFromEventId" in event and event["resumedFromEventId"] is not None:
        resumed = event["resumedFromEventId"]
        if (
            not isinstance(resumed, str)
            or len(resumed) != EVENT_ID_HEX_LEN
            or any(c not in "0123456789abcdef" for c in resumed)
        ):
            raise CaptureSchemaError("resumedFromEventId must be 16 lowercase hex characters")

    _privacy_scan(event)


def validate_event_against_schema_document(
    event: Mapping[str, Any], schema: Mapping[str, Any] | None = None
) -> None:
    """Conformance helper: validate required/enum constraints from the schema document."""
    doc = schema if schema is not None else load_schema()
    required = doc.get("required") or []
    properties = doc.get("properties") or {}
    for field in required:
        if field not in event:
            raise CaptureSchemaError(f"missing required field: {field}")
    event_type_schema = properties.get("eventType") or {}
    enum_values = event_type_schema.get("enum")
    if enum_values and event.get("eventType") not in enum_values:
        raise CaptureSchemaError(f"invalid eventType: {event.get('eventType')!r}")
    validate_event(dict(event))


__all__ = [
    "CapturePrivacyError",
    "CaptureSchemaError",
    "EVENT_TYPES",
    "PROVENANCE_KINDS",
    "SCHEMA_VERSION",
    "compute_event_id",
    "load_schema",
    "schema_path",
    "validate_event",
    "validate_event_against_schema_document",
]
