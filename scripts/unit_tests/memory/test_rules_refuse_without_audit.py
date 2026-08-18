"""PRD 277 R6 — ordinary store, memory-sync, and import refuse unapproved rule writes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_rules_promote import (
    AUDIT_COMMAND,
    RuleWriteRefused,
    content_hash,
    import_store,
    memory_sync_store,
    ordinary_store,
)

BODY = "Never auto-promote rule-class memories.\n"
APPROVAL = {
    "command": AUDIT_COMMAND,
    "ruleId": "no-auto-promote",
    "contentHash": content_hash(BODY),
    "approvedBy": "operator",
}


@pytest.mark.parametrize("fn", [ordinary_store, memory_sync_store, import_store])
def test_store_and_sync_refuse_rule_class_without_audit(fn) -> None:
    with pytest.raises(RuleWriteRefused) as exc:
        fn(category="rule", rule_id="no-auto-promote", body=BODY, approval=None)
    assert exc.value.cause == "rule-write-unapproved"


@pytest.mark.parametrize("fn", [ordinary_store, memory_sync_store, import_store])
def test_non_rule_store_still_allowed(fn) -> None:
    result = fn(category="learning", rule_id="", body="a lesson")
    assert result["verdict"] == "ok"


@pytest.mark.parametrize("fn", [ordinary_store, memory_sync_store, import_store])
def test_approved_rule_write_passes(fn) -> None:
    result = fn(
        category="rule",
        rule_id="no-auto-promote",
        body=BODY,
        approval=APPROVAL,
    )
    assert result["verdict"] == "ok"
