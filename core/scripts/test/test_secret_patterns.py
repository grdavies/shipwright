"""Per-pattern deny-list coverage (PRD 079 R18)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from memory_redact import redact  # noqa: E402
from secret_patterns import DENY_PATTERNS  # noqa: E402

_PATTERN_SAMPLES: dict[str, str] = {
    "AWS_KEY": "AKIA" + "A" * 16,
    "GITHUB_PAT": "ghp_" + "a" * 36,
    "GITHUB_PAT_FINE": "github_pat_" + "A" * 22,
    "GITHUB_OAUTH": "gho_" + "a" * 36,
    "GITHUB_USER": "ghu_" + "a" * 36,
    "GITHUB_SERVER": "ghs_" + "a" * 36,
    "GITHUB_REFRESH": "ghr_" + "a" * 36,
    "BEARER_TOKEN": "Bearer " + "a" * 20,
    "JWT": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "PEM_PRIVATE_KEY": "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----",
    "EMAIL": "user@example.com",
    "DB_URL": "postgresql://user:pass@db.example.com:5432/app",
    "WEBHOOK_SECRET": "whsec_" + "a" * 12,
    "API_SECRET": "sk_live_" + "a" * 12,
    "API_RESTRICTED_KEY": "rk_live_" + "a" * 12,
    "HIGH_ENTROPY_SECRET": 'api_key="abcdefghijklmnopqrstuvwxyz"',
    "INTERNAL_IP": "10.0.0.1",
    "INTERNAL_HOST": "svc.cluster.local",
    "SENTRY_PII_JSON": '"user_id": "abc123"',
    "SENTRY_PII_KV": "username=alice",
}


@pytest.mark.parametrize("deny", DENY_PATTERNS, ids=[p.name for p in DENY_PATTERNS])
def test_deny_pattern_has_coverage_sample(deny: object) -> None:
    pattern = deny  # type: ignore[assignment]
    sample = _PATTERN_SAMPLES.get(pattern.name)
    assert sample is not None, f"missing coverage sample for {pattern.name}"
    assert pattern.pattern.search(sample), f"sample does not match {pattern.name}"


def test_github_pat_fine_grained_prefix_present() -> None:
    names = {p.name for p in DENY_PATTERNS}
    assert "GITHUB_PAT_FINE" in names
    fine = next(p for p in DENY_PATTERNS if p.name == "GITHUB_PAT_FINE")
    assert "github_pat_" in fine.pattern.pattern


def test_redact_github_pat_fine_grained() -> None:
    token = "github_pat_" + "X" * 30
    redacted = redact(f"Authorization: {token}")
    assert "github_pat_" not in redacted
    assert "[REDACTED:GITHUB_PAT_FINE]" in redacted
