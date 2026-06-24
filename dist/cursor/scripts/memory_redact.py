#!/usr/bin/env python3
"""Deterministic R41 redaction chokepoint — stdin or file arg → stdout."""
import re
import sys
from pathlib import Path

REDACTIONS = [
    (re.compile(r"AKIA[0-9A-Z]{16}"), "[REDACTED:AWS_KEY]"),
    (re.compile(r"ghp_[A-Za-z0-9]{36,}"), "[REDACTED:GITHUB_PAT]"),
    (re.compile(r"gho_[A-Za-z0-9]{36,}"), "[REDACTED:GITHUB_OAUTH]"),
    (re.compile(r"ghu_[A-Za-z0-9]{36,}"), "[REDACTED:GITHUB_USER]"),
    (re.compile(r"ghs_[A-Za-z0-9]{36,}"), "[REDACTED:GITHUB_SERVER]"),
    (re.compile(r"ghr_[A-Za-z0-9]{36,}"), "[REDACTED:GITHUB_REFRESH]"),
    (re.compile(r"(?:Authorization:\s*)?Bearer\s+[A-Za-z0-9._~+/=-]{8,}", re.IGNORECASE), "Bearer [REDACTED:TOKEN]"),
    (re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"), "[REDACTED:JWT]"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----[\s\S]*?"
            r"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
        ),
        "[REDACTED:PEM_PRIVATE_KEY]",
    ),
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "[REDACTED:EMAIL]"),
    (re.compile(r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://\S+"), "[REDACTED:DB_URL]"),
    (re.compile(r"whsec_[A-Za-z0-9]+"), "[REDACTED:WEBHOOK_SECRET]"),
    (re.compile(r"sk_(?:live|test)_[A-Za-z0-9]+"), "[REDACTED:API_SECRET]"),
    (re.compile(r"rk_(?:live|test)_[A-Za-z0-9]+"), "[REDACTED:API_RESTRICTED_KEY]"),
    (
        re.compile(
            r"(?i)(?:password|secret|token|api[_-]?key)\s*[=:]\s*['\"]?[^\s'\"]{20,}['\"]?"
        ),
        "[REDACTED:HIGH_ENTROPY_SECRET]",
    ),
    (
        re.compile(
            r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
            r"172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|"
            r"192\.168\.\d{1,3}\.\d{1,3})\b"
        ),
        "[REDACTED:INTERNAL_IP]",
    ),
    (re.compile(r"(?i)\b[\w.-]+\.(?:internal|local|localhost)\b"), "[REDACTED:INTERNAL_HOST]"),
    (
        re.compile(
            r'(?i)"(?:user[_-]?id|username|ip_address)"\s*:\s*"(?:[^"\\]|\\.)*"'
        ),
        '"[REDACTED:SENTRY_PII]"',
    ),
    (
        re.compile(r"(?i)(?:user[_-]?id|username|ip_address)\s*[=:]\s*\S+"),
        "[REDACTED:SENTRY_PII]",
    ),
]


def redact(text: str) -> str:
    out = text
    for pattern, replacement in REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


def main() -> None:
    if len(sys.argv) > 1:
        text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
    else:
        text = sys.stdin.read()
    sys.stdout.write(redact(text))


if __name__ == "__main__":
    main()
