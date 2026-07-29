#!/usr/bin/env python3
"""Allowlist, escape spans, substitution budget, and redaction orchestration (PRD 082 R32)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from memory_entropy_detector import (
    ADVISORY_DESTINATIONS,
    MANDATORY_DESTINATIONS,
    EntropyFinding,
    detect_high_entropy,
    enforce_entropy_findings,
)
from memory_redact_patterns import (
    MODERN_PATTERNS,
    apply_modern_patterns,
    pattern_set_version,
    scan_residual_modern_patterns,
)

DESTINATION_VALUES = frozenset({"local", "committed", "external", "cross-project", "logs"})

ESCAPE_START = "[sw-redact-keep]"
ESCAPE_END = "[/sw-redact-keep]"
ESCAPE_SPAN_RE = re.compile(
    re.escape(ESCAPE_START) + r"(.*?)" + re.escape(ESCAPE_END),
    re.DOTALL,
)

DEFAULT_SUBSTITUTION_BUDGET = 64

GIT_SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
CONTENT_HASH_RE = re.compile(r"\b[0-9a-f]{64}\b")
BASE64_FIXTURE_RE = re.compile(r"\b(?:dGVzd[A-Za-z0-9+/=]{0,40}={0,2}|Zm9v[A-Za-z0-9+/=]{0,40}={0,2})\b")

OVERRIDE_JOURNAL_DIR = Path(".cursor") / "sw-memory-redact-override-journal"
OVERRIDE_JOURNAL_SCHEMA_VERSION = 1


class RedactionBudgetError(Exception):
    """Raised when per-document substitution budget is exceeded."""


class RedactionResidualError(Exception):
    def __init__(self, message: str, *, detector: str | None = None) -> None:
        super().__init__(message)
        self.detector = detector


@dataclass
class AdvisoryReport:
    destination: str
    entropy_findings: list[EntropyFinding] = field(default_factory=list)
    residual_detectors: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "destination": self.destination,
            "entropyFindings": [
                {
                    "token": f.token,
                    "charset": f.charset,
                    "entropy": round(f.entropy, 4),
                    "threshold": f.threshold,
                    "start": f.start,
                    "end": f.end,
                }
                for f in self.entropy_findings
            ],
            "residualDetectors": dict(self.residual_detectors),
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect_allowlisted_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for match in GIT_SHA_RE.finditer(text):
        spans.append((match.start(), match.end()))
    for match in UUID_RE.finditer(text):
        spans.append((match.start(), match.end()))
    for match in CONTENT_HASH_RE.finditer(text):
        spans.append((match.start(), match.end()))
    for match in BASE64_FIXTURE_RE.finditer(text):
        spans.append((match.start(), match.end()))
    return spans


def extract_escape_spans(text: str) -> tuple[str, list[tuple[int, int]]]:
    """Strip escape markers and record preserved inner spans in the working text."""
    escape_spans: list[tuple[int, int]] = []
    out_parts: list[str] = []
    cursor = 0
    offset = 0
    for match in ESCAPE_SPAN_RE.finditer(text):
        prefix = text[cursor : match.start()]
        out_parts.append(prefix)
        offset += len(prefix)
        inner = match.group(1)
        start = offset
        out_parts.append(inner)
        offset += len(inner)
        escape_spans.append((start, offset))
        cursor = match.end()
    out_parts.append(text[cursor:])
    return "".join(out_parts), escape_spans


def merge_spans(*groups: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for group in groups:
        merged.extend(group)
    return merged


def _mask_spans(text: str, spans: list[tuple[int, int]]) -> tuple[str, list[tuple[str, int]]]:
    """Replace protected spans with placeholders so substitutions skip them."""
    if not spans:
        return text, []
    ordered = sorted(spans, key=lambda item: item[0])
    parts: list[str] = []
    placeholders: list[tuple[str, int]] = []
    cursor = 0
    for index, (start, end) in enumerate(ordered):
        parts.append(text[cursor:start])
        token = f"\x00SW_PROTECT_{index}\x00"
        placeholders.append((token, end - start))
        parts.append(token)
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts), placeholders


def _mask_residual_scan(text: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return text
    masked, _placeholders = _mask_spans(text, spans)
    for index, (start, end) in enumerate(sorted(spans, key=lambda item: item[0])):
        placeholder = f"\x00SW_PROTECT_{index}\x00"
        masked = masked.replace(placeholder, " " * (end - start), 1)
    return masked


def _unmask_spans(text: str, placeholders: list[tuple[str, int]], originals: list[tuple[int, int]], source: str) -> str:
    out = text
    for (token, length), (start, _end) in zip(placeholders, originals):
        original = source[start : start + length]
        out = out.replace(token, original, 1)
    return out


def apply_with_budget(text: str, budget: int, *, protected_spans: list[tuple[int, int]] | None = None) -> tuple[str, int]:
    protected = protected_spans or []
    masked, placeholders = _mask_spans(text, protected)
    out, count = apply_modern_patterns(masked)
    out = _unmask_spans(out, placeholders, protected, text)
    if count > budget:
        raise RedactionBudgetError(f"substitution budget exceeded: {count}>{budget}")
    return out, count


def redact_document(
    text: str,
    *,
    destination: str,
    substitution_budget: int = DEFAULT_SUBSTITUTION_BUDGET,
) -> tuple[str, dict[str, Any]]:
    """Full modern-token + entropy redaction pipeline with allowlist and budget."""
    if destination not in DESTINATION_VALUES:
        raise ValueError(f"invalid destination: {destination!r}")

    stripped, escape_spans = extract_escape_spans(text)
    allowlisted = collect_allowlisted_spans(stripped)
    protected_spans = merge_spans(allowlisted, escape_spans)

    substituted, substitution_count = apply_with_budget(
        stripped,
        substitution_budget,
        protected_spans=protected_spans,
    )

    entropy_findings = detect_high_entropy(
        substituted,
        destination=destination,
        allowlisted_spans=protected_spans,
    )
    redacted, enforced_findings = enforce_entropy_findings(
        substituted,
        entropy_findings,
        destination=destination,
    )

    residuals = scan_residual_modern_patterns(_mask_residual_scan(redacted, protected_spans))
    advisory = AdvisoryReport(
        destination=destination,
        entropy_findings=enforced_findings if destination in ADVISORY_DESTINATIONS else [],
        residual_detectors=residuals if destination in ADVISORY_DESTINATIONS else {},
    )

    if residuals and destination in MANDATORY_DESTINATIONS:
        detector = sorted(residuals)[0]
        raise RedactionResidualError(f"residual:{detector}", detector=detector)

    provenance = {
        "destinationTierApplied": destination,
        "patternSetVersion": pattern_set_version(),
        "substitutionCount": substitution_count,
        "entropyFindingCount": len(enforced_findings),
        "advisory": advisory.to_dict() if destination in ADVISORY_DESTINATIONS else None,
    }
    return redacted, provenance


def _journal_path(root: Path, scope: str = "default") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (scope or "default").strip()) or "default"
    return root / OVERRIDE_JOURNAL_DIR / f"{safe}.json"


def load_override_journal(root: Path, *, scope: str = "default") -> dict[str, Any]:
    path = _journal_path(root, scope)
    if not path.is_file():
        return {
            "schemaVersion": OVERRIDE_JOURNAL_SCHEMA_VERSION,
            "scope": scope,
            "entries": [],
            "updatedAt": utc_now_iso(),
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schemaVersion": OVERRIDE_JOURNAL_SCHEMA_VERSION,
            "scope": scope,
            "entries": [],
            "updatedAt": utc_now_iso(),
        }
    if not isinstance(doc, dict):
        return {
            "schemaVersion": OVERRIDE_JOURNAL_SCHEMA_VERSION,
            "scope": scope,
            "entries": [],
            "updatedAt": utc_now_iso(),
        }
    doc.setdefault("entries", [])
    return doc


def record_detector_override(
    root: Path,
    *,
    detector: str,
    actor: str,
    reason: str,
    scope: str = "default",
) -> dict[str, Any]:
    """Human-gated detector override journal entry (append-only)."""
    if not actor.strip():
        raise ValueError("override actor is required")
    if not reason.strip():
        raise ValueError("override reason is required")
    journal = load_override_journal(root, scope=scope)
    entry = {
        "detector": detector.strip(),
        "actor": actor.strip(),
        "reason": reason.strip(),
        "recordedAt": utc_now_iso(),
    }
    body = json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    entry["digest"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    entries = list(journal.get("entries") or [])
    entries.append(entry)
    journal["entries"] = entries
    journal["updatedAt"] = utc_now_iso()
    path = _journal_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(journal, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"verdict": "recorded", "entry": entry, "journalPath": str(path)}


def modern_pattern_names() -> list[str]:
    return sorted(p.name for p in MODERN_PATTERNS)
