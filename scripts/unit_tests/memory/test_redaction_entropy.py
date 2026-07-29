"""PRD 082 R32 — entropy, allowlist, escape, and budget fixtures."""
from __future__ import annotations

import secrets
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import memory_entropy_detector as entropy  # noqa: E402
import memory_redact_allowlist as allowlist  # noqa: E402
import memory_envelope_v2 as env  # noqa: E402


def test_allowlist_spares_git_sha_uuid_and_content_hash() -> None:
    git_sha = "a" * 40
    uuid = "12345678-1234-5678-9abc-1234567890ab"
    envelope = env.new_envelope(
        stable_id="mem-1",
        project_id="shipwright",
        category="learning",
        sensitivity="internal",
    )
    content_hash = env.compute_content_hash(envelope)
    body = f"sha={git_sha} id={uuid} hash={content_hash}"
    findings = entropy.detect_high_entropy(body, destination="external")
    assert findings == []


def test_random_forty_character_token_is_flagged_for_external() -> None:
    token = secrets.token_urlsafe(30)
    body = f"maybe-secret {token}"
    findings = entropy.detect_high_entropy(body, destination="external")
    assert any(f.token == token for f in findings)


def test_escaped_span_is_exempt_from_redaction() -> None:
    token = "npm_" + "Z" * 36
    body = f"before {allowlist.ESCAPE_START}{token}{allowlist.ESCAPE_END} after"
    redacted, record = allowlist.redact_document(body, destination="external")
    assert token in redacted
    assert record["substitutionCount"] == 0


def test_budget_exceeded_fails_closed_without_mangling() -> None:
    from memory_redact_patterns import CORPUS_SAMPLES

    body = " ".join(CORPUS_SAMPLES[name] for name in sorted(CORPUS_SAMPLES))
    with pytest.raises(allowlist.RedactionBudgetError):
        allowlist.redact_document(body, destination="external", substitution_budget=2)
    assert "ghp_" in body


def test_advisory_destination_surfaces_structured_report() -> None:
    token = secrets.token_urlsafe(30)
    body = f"maybe-secret {token}"
    redacted, record = allowlist.redact_document(body, destination="committed")
    assert redacted == body
    advisory = record["advisory"]
    assert advisory is not None
    assert advisory["destination"] == "committed"
    assert advisory["entropyFindings"]


def test_detector_override_is_journaled(tmp_path: Path) -> None:
    result = allowlist.record_detector_override(
        tmp_path,
        detector="HIGH_ENTROPY:HEX",
        actor="operator",
        reason="false positive in fixture corpus",
    )
    assert result["verdict"] == "recorded"
    journal = allowlist.load_override_journal(tmp_path)
    assert len(journal["entries"]) == 1
    assert journal["entries"][0]["actor"] == "operator"
