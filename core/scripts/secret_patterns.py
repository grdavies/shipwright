#!/usr/bin/env python3
"""Single source for deny/redaction patterns (R41/R51). Used by memory_redact.py and secret_scan.py."""
from __future__ import annotations

import re
from typing import NamedTuple


class DenyPattern(NamedTuple):
    name: str
    pattern: re.Pattern[str]
    replacement: str


def _patterns() -> list[DenyPattern]:
    specs: list[tuple[str, str, str]] = [
        ("AWS_KEY", r"AKIA[0-9A-Z]{16}", "[REDACTED:AWS_KEY]"),
        ("GITHUB_PAT", r"ghp_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_PAT]"),
        ("GITHUB_OAUTH", r"gho_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_OAUTH]"),
        ("GITHUB_USER", r"ghu_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_USER]"),
        ("GITHUB_SERVER", r"ghs_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_SERVER]"),
        ("GITHUB_REFRESH", r"ghr_[A-Za-z0-9]{36,}", "[REDACTED:GITHUB_REFRESH]"),
        (
            "BEARER_TOKEN",
            r"(?:Authorization:\s*)?Bearer\s+[A-Za-z0-9._~+/=-]{8,}",
            "Bearer [REDACTED:TOKEN]",
        ),
        ("JWT", r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED:JWT]"),
        (
            "PEM_PRIVATE_KEY",
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
            "[REDACTED:PEM_PRIVATE_KEY]",
        ),
        (
            "EMAIL",
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
            "[REDACTED:EMAIL]",
        ),
        (
            "DB_URL",
            r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://\S+",
            "[REDACTED:DB_URL]",
        ),
        ("WEBHOOK_SECRET", r"whsec_[A-Za-z0-9]+", "[REDACTED:WEBHOOK_SECRET]"),
        ("API_SECRET", r"sk_(?:live|test)_[A-Za-z0-9]+", "[REDACTED:API_SECRET]"),
        (
            "API_RESTRICTED_KEY",
            r"rk_(?:live|test)_[A-Za-z0-9]+",
            "[REDACTED:API_RESTRICTED_KEY]",
        ),
        (
            "HIGH_ENTROPY_SECRET",
            r"(?i)(?:password|secret|token|api[_-]?key)\s*[=:]\s*['\"]?[^\s'\"]{20,}['\"]?",
            "[REDACTED:HIGH_ENTROPY_SECRET]",
        ),
        (
            "INTERNAL_IP",
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3})\b",
            "[REDACTED:INTERNAL_IP]",
        ),
        (
            "INTERNAL_HOST",
            r"(?i)(?:\b[\w.-]+\.internal\b|\b[\w.-]+\.cluster\.local\b)",
            "[REDACTED:INTERNAL_HOST]",
        ),
        (
            "SENTRY_PII_JSON",
            r'(?i)"(?:user[_-]?id|username|ip_address)"\s*:\s*"(?:[^"\\]|\\.)*"',
            '"[REDACTED:SENTRY_PII]"',
        ),
        (
            "SENTRY_PII_KV",
            r"(?i)(?:user[_-]?id|username|ip_address)\s*[=:]\s*\S+",
            "[REDACTED:SENTRY_PII]",
        ),
    ]
    out: list[DenyPattern] = []
    for name, raw, replacement in specs:
        flags = re.IGNORECASE if "(?i)" in raw else 0
        cleaned = raw.replace("(?i)", "")
        out.append(DenyPattern(name, re.compile(cleaned, flags), replacement))
    return out


DENY_PATTERNS: list[DenyPattern] = _patterns()
REDACTIONS: list[tuple[re.Pattern[str], str]] = [(p.pattern, p.replacement) for p in DENY_PATTERNS]
