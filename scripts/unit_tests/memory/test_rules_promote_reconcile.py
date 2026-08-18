"""PRD 277 R10 — allowlist only after verified write; else needs-reconcile."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import PreflightError, rules_load
from memory_rules_promote import (
    ALLOWLIST_REL,
    content_hash,
    needs_reconcile_path,
    promote_rule,
)

BODY = "Reconcile fixture.\n"
RULE_ID = "reconcile-rule"


def _approval() -> dict:
    return {
        "command": "sw-memory-audit",
        "ruleId": RULE_ID,
        "contentHash": content_hash(BODY),
        "approvedBy": "operator",
        "provenance": "sw-memory-audit",
    }


def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("memory_rules_promote.configured_provider", lambda root: "recallium")
    monkeypatch.setattr(
        "memory_rules_promote.assert_provider_registered",
        lambda root, provider: {"ok": True, "provider": provider},
    )
    monkeypatch.setattr("memory_preflight.configured_provider", lambda root: "recallium")
    monkeypatch.setattr(
        "memory_preflight.validate_registration",
        lambda root, provider: {"ok": True, "provider": provider},
    )


def test_allowlist_after_verified_write_else_needs_reconcile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_provider(monkeypatch)
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": "recallium", "project": "t"}}),
        encoding="utf-8",
    )

    failed = promote_rule(
        tmp_path,
        rule_id=RULE_ID,
        body=BODY,
        approval=_approval(),
        writer=lambda root, payload: {"verdict": "fail", "error": "adapter down"},
    )
    assert failed["needsReconcile"] is True
    assert needs_reconcile_path(tmp_path).is_file()
    allowlist_path = tmp_path / ALLOWLIST_REL
    assert not allowlist_path.is_file() or RULE_ID not in json.loads(
        allowlist_path.read_text(encoding="utf-8")
    )
    with pytest.raises(PreflightError) as exc:
        rules_load(tmp_path, loader=lambda root, provider: {"rules": []})
    assert exc.value.cause == "needs-reconcile"

    ok = promote_rule(
        tmp_path,
        rule_id=RULE_ID,
        body=BODY,
        approval=_approval(),
        writer=lambda root, payload: {"verdict": "ok", "writtenVia": "fixture"},
    )
    assert ok["needsReconcile"] is False
    assert RULE_ID in ok["allowlist"]
    assert not needs_reconcile_path(tmp_path).is_file()
    loaded = rules_load(
        tmp_path,
        loader=lambda root, provider: {"rules": [{"id": RULE_ID, "body": BODY}]},
    )
    assert any(entry.get("id") == RULE_ID for entry in loaded["rules"])
