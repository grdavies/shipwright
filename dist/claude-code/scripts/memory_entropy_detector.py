#!/usr/bin/env python3
"""Keyword-independent Shannon entropy detector for memory redaction (PRD 082 R32)."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

CharsetKind = Literal["hex", "base64", "base64url", "alphanumeric", "other"]

MANDATORY_DESTINATIONS = frozenset({"external", "cross-project", "logs"})
ADVISORY_DESTINATIONS = frozenset({"local", "committed"})

MIN_TOKEN_LENGTH = 20

CHARSET_THRESHOLDS: dict[CharsetKind, float] = {
    "hex": 3.2,
    "base64": 4.2,
    "base64url": 4.2,
    "alphanumeric": 3.8,
    "other": 4.5,
}

TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9+/=_-]+")


@dataclass(frozen=True)
class EntropyFinding:
    token: str
    charset: CharsetKind
    entropy: float
    threshold: float
    start: int
    end: int


def shannon_entropy(token: str) -> float:
    if not token:
        return 0.0
    counts: dict[str, int] = {}
    for ch in token:
        counts[ch] = counts.get(ch, 0) + 1
    length = len(token)
    entropy = 0.0
    for count in counts.values():
        probability = count / length
        entropy -= probability * math.log2(probability)
    return entropy


def classify_charset(token: str) -> CharsetKind:
    if re.fullmatch(r"[0-9a-fA-F]+", token):
        return "hex"
    if re.fullmatch(r"[A-Za-z0-9+/=]+", token) and "=" in token:
        return "base64"
    if re.fullmatch(r"[A-Za-z0-9_-]+", token) and ("-" in token or "_" in token):
        return "base64url"
    if re.fullmatch(r"[A-Za-z0-9]+", token):
        return "alphanumeric"
    return "other"


def iter_delimiter_tokens(text: str) -> list[tuple[str, int, int]]:
    tokens: list[tuple[str, int, int]] = []
    pos = 0
    for part in TOKEN_SPLIT_RE.split(text):
        if not part:
            continue
        start = text.find(part, pos)
        if start < 0:
            continue
        end = start + len(part)
        tokens.append((part, start, end))
        pos = end
    return tokens


def detect_high_entropy(
    text: str,
    *,
    destination: str,
    allowlisted_spans: list[tuple[int, int]] | None = None,
    min_length: int = MIN_TOKEN_LENGTH,
) -> list[EntropyFinding]:
    """Detect high-entropy tokens; enforcement posture depends on destination tier."""
    if destination not in MANDATORY_DESTINATIONS | ADVISORY_DESTINATIONS:
        raise ValueError(f"invalid destination: {destination!r}")

    spans = allowlisted_spans or []
    findings: list[EntropyFinding] = []

    def span_allowed(start: int, end: int) -> bool:
        return any(start >= lo and end <= hi for lo, hi in spans)

    for token, start, end in iter_delimiter_tokens(text):
        if len(token) < min_length:
            continue
        if span_allowed(start, end):
            continue
        charset = classify_charset(token)
        entropy = shannon_entropy(token)
        threshold = CHARSET_THRESHOLDS[charset]
        if entropy >= threshold:
            findings.append(
                EntropyFinding(
                    token=token,
                    charset=charset,
                    entropy=entropy,
                    threshold=threshold,
                    start=start,
                    end=end,
                )
            )
    return findings


def enforce_entropy_findings(
    text: str,
    findings: list[EntropyFinding],
    *,
    destination: str,
) -> tuple[str, list[EntropyFinding]]:
    """Apply mandatory redaction for external tiers; advisory-only for committed/local."""
    if destination in ADVISORY_DESTINATIONS:
        return text, findings

    if not findings:
        return text, []

    out = text
    # Replace from the end so offsets stay valid.
    for finding in sorted(findings, key=lambda f: f.start, reverse=True):
        replacement = f"[REDACTED:HIGH_ENTROPY:{finding.charset.upper()}]"
        out = out[: finding.start] + replacement + out[finding.end :]
    return out, findings


def is_mandatory_destination(destination: str) -> bool:
    return destination in MANDATORY_DESTINATIONS
