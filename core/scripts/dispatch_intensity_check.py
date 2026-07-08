#!/usr/bin/env python3
"""Shared intensity-directive format + structural-anchor validation (PRD 058 R7/R8/R12)."""
from __future__ import annotations

import re
from dataclasses import dataclass

ALLOWED_INTENSITIES = frozenset({"normal", "lite", "full", "ultra"})

_RETRIEVE_KEY_PATTERN = re.compile(r"\bretrieveKey\b")
_RETRIEVE_CALL_PATTERN = re.compile(r"\bretrieve\s*\(")

# Canonical literal line sourced from guardrail_core.build_session_context().
_INTENSITY_LINE_RE = re.compile(
    r"^\*\*Resolved intensity:\*\* `(?P<intensity>normal|lite|full|ultra)` \((?P<source>[^)]+)\)\s*(?:\n|$)"
)


@dataclass(frozen=True)
class DirectiveAnchorResult:
    verdict: str  # pass | fail
    intensity: str | None = None
    source: str | None = None
    cause: str | None = None
    remediation: str | None = None


@dataclass(frozen=True)
class RetrieveKeyGuardResult:
    verdict: str  # pass | fail
    cause: str | None = None
    remediation: str | None = None


def validate_retrieve_key_guard(prompt: str) -> RetrieveKeyGuardResult:
    """Confirm retrieveKey/retrieve() never appear in outbound Task prompt text (R23)."""
    if not isinstance(prompt, str):
        return RetrieveKeyGuardResult(verdict="pass")

    if _RETRIEVE_KEY_PATTERN.search(prompt):
        return RetrieveKeyGuardResult(
            verdict="fail",
            cause="binding:retrieve-key-in-prompt",
            remediation=(
                "retrieveKey is orchestrator-only; keep cache keys out of subagent-visible "
                "prompt text and use orchestrator-side retrieve() re-dispatch"
            ),
        )

    if _RETRIEVE_CALL_PATTERN.search(prompt):
        return RetrieveKeyGuardResult(
            verdict="fail",
            cause="binding:retrieve-call-in-prompt",
            remediation=(
                "retrieve() is orchestrator-only; never embed cache retrieval calls in "
                "subagent-visible prompt text"
            ),
        )

    return RetrieveKeyGuardResult(verdict="pass")


def format_intensity_directive(intensity: str, source: str) -> str:
    """Return the canonical leading-line intensity directive block for Task prompts."""
    if intensity not in ALLOWED_INTENSITIES:
        raise ValueError(f"invalid intensity: {intensity!r}")
    clean_source = source.strip()
    if not clean_source:
        raise ValueError("source must be non-empty")
    return f"**Resolved intensity:** `{intensity}` ({clean_source})\n"


def _intensity_line_pattern() -> re.Pattern[str]:
    return re.compile(
        r"\*\*Resolved intensity:\*\* `(?P<intensity>normal|lite|full|ultra)` \((?P<source>[^)]+)\)"
    )


def parse_anchored_directive(prompt: str) -> tuple[str, str] | None:
    """Parse intensity/source when the directive is structurally anchored at prompt start."""
    if not isinstance(prompt, str):
        return None
    match = _INTENSITY_LINE_RE.match(prompt.lstrip("\ufeff"))
    if not match:
        return None
    return match.group("intensity"), match.group("source")


def _directive_line_elsewhere(prompt: str) -> bool:
    """True when a directive-shaped line appears after the anchored leading position."""
    normalized = prompt.lstrip("\ufeff")
    match = _INTENSITY_LINE_RE.match(normalized)
    if match:
        remainder = normalized[match.end() :]
    else:
        remainder = normalized
    return _intensity_line_pattern().search(remainder) is not None


def validate_directive_anchor(
    prompt: str,
    *,
    expected_intensity: str | None = None,
    expected_source: str | None = None,
) -> DirectiveAnchorResult:
    """Validate the R7 directive block is present at the fixed leading anchor (R8)."""
    if not isinstance(prompt, str):
        return DirectiveAnchorResult(
            verdict="fail",
            cause="binding:missing-intensity-directive",
            remediation="embed format_intensity_directive() as the first line of tool_input.prompt",
        )

    parsed = parse_anchored_directive(prompt)
    if parsed is None:
        if _intensity_line_pattern().search(prompt):
            return DirectiveAnchorResult(
                verdict="fail",
                cause="binding:directive-not-anchored",
                remediation=(
                    "move the intensity directive to the leading line of tool_input.prompt; "
                    "do not rely on incidental matches inside untrusted payload text"
                ),
            )
        return DirectiveAnchorResult(
            verdict="fail",
            cause="binding:missing-intensity-directive",
            remediation="prepend format_intensity_directive(intensity, source) to tool_input.prompt",
        )

    intensity, source = parsed
    if _directive_line_elsewhere(prompt):
        return DirectiveAnchorResult(
            verdict="fail",
            cause="binding:directive-not-anchored",
            intensity=intensity,
            source=source,
            remediation=(
                "keep a single leading intensity directive; remove duplicate directive tokens "
                "from untrusted payload text"
            ),
        )

    if expected_intensity is not None and intensity != expected_intensity:
        return DirectiveAnchorResult(
            verdict="fail",
            intensity=intensity,
            source=source,
            cause="binding:intensity-mismatch",
            remediation=format_intensity_directive(expected_intensity, source).rstrip("\n"),
        )
    if expected_source is not None and source != expected_source.strip():
        return DirectiveAnchorResult(
            verdict="fail",
            intensity=intensity,
            source=source,
            cause="binding:intensity-mismatch",
            remediation=format_intensity_directive(intensity, expected_source).rstrip("\n"),
        )

    return DirectiveAnchorResult(
        verdict="pass",
        intensity=intensity,
        source=source,
    )
