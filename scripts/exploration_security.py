#!/usr/bin/env python3
"""Brokered memory access and redacted exploration artifact output (PRD 331 R19, R43, R44)."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping

import memory_preflight
import memory_redact
from memory_preflight import PreflightError
from planning_visibility import resolve_emission_destination

SECRET_KEY_PATTERN = re.compile(
    r"(apiKey|token|password|secret|credential|privateKey|accessToken)",
    re.IGNORECASE,
)
SECRET_VALUE_PATTERN = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|password\s*=)",
)

ARTIFACT_KINDS = frozenset({"map", "status", "projection"})


class ExplorationSecurityError(RuntimeError):
    """Exploration security boundary violation."""


class MemoryBrokerRefusedError(ExplorationSecurityError):
    """Historical lookup refused by memory preflight / broker."""


HistoricalQueryFn = Callable[[Path, str, dict[str, Any]], dict[str, Any]]


def _scan_secret_violations(document: Mapping[str, Any], prefix: str = "") -> list[str]:
    violations: list[str] = []
    for key, value in document.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if SECRET_KEY_PATTERN.search(str(key)):
            violations.append(f"forbidden-key:{path}")
        if isinstance(value, str) and SECRET_VALUE_PATTERN.search(value):
            violations.append(f"forbidden-value:{path}")
        elif isinstance(value, dict):
            violations.extend(_scan_secret_violations(value, path))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    violations.extend(_scan_secret_violations(item, f"{path}[{index}]"))
                elif isinstance(item, str) and SECRET_VALUE_PATTERN.search(item):
                    violations.append(f"forbidden-value:{path}[{index}]")
    return violations


def assert_secret_free(document: Mapping[str, Any]) -> None:
    violations = _scan_secret_violations(document)
    if violations:
        raise ExplorationSecurityError(violations[0])


def _redact_text(text: str, *, destination: str) -> str:
    try:
        return memory_redact.redact(text, destination=destination)
    except memory_redact.RedactionError as exc:
        raise ExplorationSecurityError(str(exc)) from exc


def redact_exploration_payload(
    document: Mapping[str, Any],
    *,
    artifact_kind: str,
) -> dict[str, Any]:
    """Redact secrets from canonical maps, status, and projection payloads (R43)."""
    if artifact_kind not in ARTIFACT_KINDS:
        raise ExplorationSecurityError("invalid-artifact-kind")
    destination = resolve_emission_destination("dispatch-context")
    redacted = deepcopy(dict(document))

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            return _redact_text(value, destination=destination)
        if isinstance(value, list):
            return [_walk(item) for item in value]
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                if SECRET_KEY_PATTERN.search(str(key)):
                    continue
                cleaned[key] = _walk(item)
            return cleaned
        return value

    result = _walk(redacted)
    if not isinstance(result, dict):
        raise ExplorationSecurityError("redaction-shape-invalid")
    assert_secret_free(result)
    return result


def lookup_historical_context(
    root: Path,
    query: str,
    *,
    preflight: Callable[[Path], dict[str, Any]] | None = None,
    query_fn: HistoricalQueryFn | None = None,
) -> dict[str, Any]:
    """Route historical lookup through memory-preflight before any provider query (R19)."""
    loader = preflight or memory_preflight.preflight
    try:
        preflight_result = loader(root)
    except PreflightError as exc:
        return {
            "verdict": "degraded",
            "cause": exc.cause,
            "results": [],
            "redacted": True,
        }
    if preflight_result.get("verdict") != "ok":
        return {
            "verdict": "degraded",
            "cause": str(preflight_result.get("cause") or "preflight-failed"),
            "results": [],
            "redacted": True,
        }
    if query_fn is None:
        return {
            "verdict": "ok",
            "provider": preflight_result.get("provider"),
            "results": [],
            "redacted": True,
            "note": "no-query-fn",
        }
    try:
        raw = query_fn(root, query, preflight_result)
    except PreflightError as exc:
        return {
            "verdict": "degraded",
            "cause": exc.cause,
            "results": [],
            "redacted": True,
        }
    except Exception as exc:  # noqa: BLE001 — broker boundary
        return {
            "verdict": "degraded",
            "cause": "broker-refused",
            "results": [],
            "redacted": True,
            "error": str(exc),
        }
    results = raw.get("results") if isinstance(raw.get("results"), list) else []
    destination = resolve_emission_destination("dispatch-context")
    redacted_results: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        snippet = str(item.get("snippet") or item.get("text") or "")
        redacted_results.append(
            {
                **item,
                "snippet": _redact_text(snippet, destination=destination),
                "redacted": True,
            }
        )
    return {
        "verdict": "ok",
        "provider": preflight_result.get("provider"),
        "results": redacted_results,
        "redacted": True,
    }


def sanitize_projection(
    projection: Mapping[str, Any],
    *,
    canonical_map: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Ensure projection remains below canonical semantics and redacts secrets (R44)."""
    sanitized = redact_exploration_payload(projection, artifact_kind="projection")
    if canonical_map is not None:
        canonical_revision = canonical_map.get("revision")
        projection_revision = sanitized.get("sourceRevision", sanitized.get("revision"))
        if projection_revision is not None and canonical_revision is not None:
            if int(projection_revision) > int(canonical_revision):
                raise ExplorationSecurityError("projection-above-canonical")
    return sanitized


def prepare_status_payload(status: Mapping[str, Any]) -> dict[str, Any]:
    """Redact exploration status for operator surfaces."""
    return redact_exploration_payload(status, artifact_kind="status")


def dumps_redacted(document: Mapping[str, Any], *, artifact_kind: str) -> str:
  return json.dumps(redact_exploration_payload(document, artifact_kind=artifact_kind), sort_keys=True)
