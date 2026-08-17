#!/usr/bin/env python3
"""Metadata-only persistence schema for reviewer metrics (PRD 273 R20)."""
from __future__ import annotations

import json
from typing import Any, Mapping

from memory_redact import redact_learning_derivation

METADATA_SCHEMA_VERSION = 1

ALLOWED_METADATA_FIELDS = frozenset(
    {
        "schemaVersion",
        "personaId",
        "modelId",
        "surface",
        "attributionWindow",
        "findingId",
        "runId",
        "terminalStatus",
        "matchReason",
        "provenanceSummary",
        "dedupKey",
        "outcomeKind",
        "recordedAt",
    }
)

FORBIDDEN_METADATA_FIELDS = frozenset(
    {
        "transcript",
        "findingBody",
        "findingText",
        "body",
        "prompt",
        "promptText",
        "patch",
        "patchDiff",
        "secret",
        "secrets",
        "rawContent",
        "content",
        "message",
        "messages",
        "diff",
        "snippet",
    }
)

REQUIRED_METADATA_FIELDS = frozenset(
    {
        "personaId",
        "modelId",
        "surface",
        "attributionWindow",
        "findingId",
        "runId",
        "terminalStatus",
        "matchReason",
        "outcomeKind",
        "recordedAt",
    }
)


class MetadataSchemaError(ValueError):
    """Raised when metadata violates the closed reviewer-metrics schema."""


def _collect_keys(payload: Mapping[str, Any], *, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in payload.items():
        full = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        keys.add(key)
        if isinstance(value, Mapping):
            keys.update(_collect_keys(value, prefix=full))
    return keys


def _find_forbidden_keys(payload: Mapping[str, Any]) -> list[str]:
    forbidden: list[str] = []
    for key in _collect_keys(payload):
        lowered = key.lower()
        if key in FORBIDDEN_METADATA_FIELDS or lowered in FORBIDDEN_METADATA_FIELDS:
            forbidden.append(key)
        for token in FORBIDDEN_METADATA_FIELDS:
            if token in lowered and token != lowered:
                forbidden.append(key)
    return sorted(set(forbidden))


def validate_metadata_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate closed metadata schema; refuse transcript/body/prompt/patch/secret fields."""
    if not isinstance(payload, Mapping):
        raise MetadataSchemaError("metadata payload must be a mapping")
    forbidden = _find_forbidden_keys(payload)
    if forbidden:
        raise MetadataSchemaError(
            f"forbidden metadata fields present: {', '.join(forbidden)}"
        )
    extra = sorted(set(payload.keys()) - ALLOWED_METADATA_FIELDS)
    if extra:
        raise MetadataSchemaError(f"unknown metadata fields: {', '.join(extra)}")
    missing = sorted(REQUIRED_METADATA_FIELDS - set(payload.keys()))
    if missing:
        raise MetadataSchemaError(f"missing required metadata fields: {', '.join(missing)}")
    version = int(payload["schemaVersion"])
    if version != METADATA_SCHEMA_VERSION:
        raise MetadataSchemaError(f"unsupported metadata schema version: {version}")
    normalized = {key: payload[key] for key in ALLOWED_METADATA_FIELDS if key in payload}
    return dict(normalized)


def redact_metadata_for_write(
    payload: Mapping[str, Any],
    *,
    may_egress: bool = False,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Redact via memory-redact before every write/export path (R20)."""
    validated = validate_metadata_payload(payload)
    residuals: dict[str, int] = {}
    redacted: dict[str, Any] = {}
    for key, value in validated.items():
        if isinstance(value, str):
            field_text, field_residuals = redact_learning_derivation(
                value,
                may_egress=may_egress,
            )
            redacted[key] = field_text
            for detector, count in field_residuals.items():
                residuals[detector] = residuals.get(detector, 0) + count
        else:
            redacted[key] = value
    return redacted, residuals


def build_metadata_record(
    *,
    persona_id: str,
    model_id: str,
    surface: str,
    attribution_window: str,
    finding_id: str,
    run_id: str,
    terminal_status: str,
    match_reason: str,
    outcome_kind: str,
    recorded_at: str,
    provenance_summary: str = "",
    dedup_key: str = "",
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "schemaVersion": METADATA_SCHEMA_VERSION,
        "personaId": persona_id,
        "modelId": model_id,
        "surface": surface,
        "attributionWindow": attribution_window,
        "findingId": finding_id,
        "runId": run_id,
        "terminalStatus": terminal_status,
        "matchReason": match_reason,
        "outcomeKind": outcome_kind,
        "recordedAt": recorded_at,
    }
    if provenance_summary:
        record["provenanceSummary"] = provenance_summary
    if dedup_key:
        record["dedupKey"] = dedup_key
    return validate_metadata_payload(record)
