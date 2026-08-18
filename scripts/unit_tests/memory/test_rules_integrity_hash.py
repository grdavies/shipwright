"""PRD 277 R11 — approval binds id + contentHash + provenance."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_rules_promote import RuleWriteRefused, content_hash, promote_rule, validate_audit_approval

BODY = "Integrity fixture.\n"
RULE_ID = "integrity-rule"


def _base_approval(**overrides: str) -> dict:
    payload = {
        "command": "sw-memory-audit",
        "ruleId": RULE_ID,
        "contentHash": content_hash(BODY),
        "approvedBy": "operator",
        "provenance": "sw-memory-audit",
    }
    payload.update(overrides)
    return payload


def test_approval_content_hash_mismatch_fail_closed() -> None:
    with pytest.raises(RuleWriteRefused) as exc:
        validate_audit_approval(
            _base_approval(contentHash="deadbeef"),
            rule_id=RULE_ID,
            body=BODY,
        )
    assert exc.value.cause == "rule-write-hash-mismatch"


def test_approval_id_and_provenance_required() -> None:
    with pytest.raises(RuleWriteRefused) as exc:
        validate_audit_approval(
            _base_approval(ruleId="other-rule"),
            rule_id=RULE_ID,
            body=BODY,
        )
    assert exc.value.cause == "rule-write-id-mismatch"
    with pytest.raises(RuleWriteRefused) as prov:
        validate_audit_approval(
            _base_approval(provenance=""),
            rule_id=RULE_ID,
            body=BODY,
        )
    assert prov.value.cause == "rule-write-provenance-missing"


def test_promote_refuses_stale_hash_pending_reapproval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("memory_rules_promote.configured_provider", lambda root: "recallium")
    monkeypatch.setattr(
        "memory_rules_promote.assert_provider_registered",
        lambda root, provider: {"ok": True, "provider": provider},
    )
    with pytest.raises(RuleWriteRefused) as exc:
        promote_rule(
            tmp_path,
            rule_id=RULE_ID,
            body=BODY,
            approval=_base_approval(contentHash="00" * 32),
            writer=lambda root, payload: {"verdict": "ok"},
        )
    assert exc.value.cause == "rule-write-hash-mismatch"
