#!/usr/bin/env python3
"""Modern token pattern corpus for memory redaction (PRD 082 R32)."""
from __future__ import annotations

import hashlib
import re
from typing import NamedTuple


class ModernPattern(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    replacement: str


def _compile_specs() -> list[ModernPattern]:
    specs: list[tuple[str, str, str]] = [
        # GitHub (modern fine-grained / app / user-to-server forms)
        ("GITHUB_PAT", r"ghp_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_PAT]"),
        ("GITHUB_PAT_FINE", r"github_pat_[A-Za-z0-9_]{22,}", "[REDACTED:GITHUB_PAT_FINE]"),
        ("GITHUB_OAUTH", r"gho_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_OAUTH]"),
        ("GITHUB_USER", r"ghu_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_USER]"),
        ("GITHUB_SERVER", r"ghs_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_SERVER]"),
        ("GITHUB_REFRESH", r"ghr_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_REFRESH]"),
        # GitLab
        ("GITLAB_PAT", r"glpat-[A-Za-z0-9_-]{20,}", "[REDACTED:GITLAB_PAT]"),
        ("GITLAB_RUNNER", r"glrt-[A-Za-z0-9_-]{20,}", "[REDACTED:GITLAB_RUNNER]"),
        ("GITLAB_TRIGGER", r"glptt-[A-Za-z0-9_-]{20,}", "[REDACTED:GITLAB_TRIGGER]"),
        ("GITLAB_CI_JOB", r"glcbt-[A-Za-z0-9_-]{20,}", "[REDACTED:GITLAB_CI_JOB]"),
        # Anthropic
        ("ANTHROPIC_API_KEY", r"sk-ant(?:-api\d+)?-[A-Za-z0-9_-]{20,}", "[REDACTED:ANTHROPIC_API_KEY]"),
        # Project-scoped keys (common SaaS prefixes)
        ("PROJECT_API_KEY", r"proj_[A-Za-z0-9]{20,}", "[REDACTED:PROJECT_API_KEY]"),
        ("PROJECT_SECRET", r"prjsec_[A-Za-z0-9]{20,}", "[REDACTED:PROJECT_SECRET]"),
        # AWS temporary session credentials
        ("AWS_TEMP_KEY", r"ASIA[0-9A-Z]{16}", "[REDACTED:AWS_TEMP_KEY]"),
        ("AWS_TEMP_SECRET", r"(?i)(?:aws[_-]?secret[_-]?access[_-]?key)\s*[=:]\s*['\"]?[A-Za-z0-9/+=]{40}['\"]?", "[REDACTED:AWS_TEMP_SECRET]"),
        # Google API keys
        ("GOOGLE_API_KEY", r"AIza[0-9A-Za-z_-]{35}", "[REDACTED:GOOGLE_API_KEY]"),
        # PGP private-key block markers
        (
            "PGP_PRIVATE_KEY_BLOCK",
            r"-----BEGIN PGP PRIVATE KEY BLOCK-----[\s\S]*?-----END PGP PRIVATE KEY BLOCK-----",
            "[REDACTED:PGP_PRIVATE_KEY_BLOCK]",
        ),
        # Slack
        ("SLACK_BOT", r"xoxb-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24,}", "[REDACTED:SLACK_BOT]"),
        ("SLACK_USER", r"xoxp-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24,}", "[REDACTED:SLACK_USER]"),
        ("SLACK_APP", r"xoxa-[0-9]{10,13}-[0-9]{10,13}-[A-Za-z0-9]{24,}", "[REDACTED:SLACK_APP]"),
        ("SLACK_WEBHOOK", r"https://hooks\.slack\.com/services/T[A-Z0-9]+/B[A-Z0-9]+/[A-Za-z0-9]+", "[REDACTED:SLACK_WEBHOOK]"),
        # npm
        ("NPM_TOKEN", r"npm_[A-Za-z0-9]{36,}", "[REDACTED:NPM_TOKEN]"),
    ]
    out: list[ModernPattern] = []
    for name, raw, replacement in specs:
        flags = re.IGNORECASE if "(?i)" in raw else 0
        cleaned = raw.replace("(?i)", "")
        out.append(ModernPattern(name, re.compile(cleaned, flags), replacement))
    return out


MODERN_PATTERNS: list[ModernPattern] = _compile_specs()
REDACTIONS: list[tuple[re.Pattern[str], str]] = [(p.pattern, p.replacement) for p in MODERN_PATTERNS]


def pattern_set_version() -> str:
    """Stable version token for the modern pattern corpus."""
    names = sorted(p.name for p in MODERN_PATTERNS)
    digest = hashlib.sha256(",".join(names).encode("utf-8")).hexdigest()[:16]
    return f"modern-patterns:{len(names)}:{digest}"


def apply_modern_patterns(text: str) -> tuple[str, int]:
    """Apply deterministic modern-token substitutions; return (text, substitution_count)."""
    out = text
    total = 0
    for pattern, replacement in REDACTIONS:
        out, count = pattern.subn(replacement, out)
        total += count
    return out, total


def scan_residual_modern_patterns(text: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in MODERN_PATTERNS:
        hits = len(entry.pattern.findall(text))
        if hits:
            counts[entry.name] = hits
    return counts


# Representative samples for corpus tests (name -> literal token).
CORPUS_SAMPLES: dict[str, str] = {
    "GITHUB_PAT": "ghp_" + "A" * 36,
    "GITHUB_PAT_FINE": "github_pat_" + "A" * 22,
    "GITHUB_OAUTH": "gho_" + "B" * 36,
    "GITLAB_PAT": "glpat-" + "C" * 20,
    "ANTHROPIC_API_KEY": "sk-ant-api03-" + "D" * 24,
    "PROJECT_API_KEY": "proj_" + "E" * 24,
    "AWS_TEMP_KEY": "ASIA" + "F" * 16,
    "GOOGLE_API_KEY": "AIza" + "G" * 35,
    "PGP_PRIVATE_KEY_BLOCK": (
        "-----BEGIN PGP PRIVATE KEY BLOCK-----\n"
        "lQOYBGexamplepayload\n"
        "-----END PGP PRIVATE KEY BLOCK-----"
    ),
    "SLACK_BOT": "xoxb-1234567890-1234567890-" + "H" * 24,
    "NPM_TOKEN": "npm_" + "I" * 36,
}
