"""PRD 277 R1/R7 — rules-promote writes through configured provider adapter."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_rules_promote import (
    AUDIT_COMMAND,
    PROVIDER_RULE_CAPABILITIES,
    SUPPORTED_PROVIDERS,
    RuleWriteRefused,
    adapter_path_for,
    content_hash,
    promote_rule,
)

REPO = SCRIPTS.parent
BODY = "Do not dual-home rule bodies for non-in-repo providers.\n"


def _approval(rule_id: str, body: str) -> dict:
    return {
        "command": AUDIT_COMMAND,
        "ruleId": rule_id,
        "contentHash": content_hash(body),
        "approvedBy": "operator",
        "approvedAt": "2026-08-18T00:00:00Z",
    }


def test_rules_promote_capability_on_all_providers() -> None:
    assert set(SUPPORTED_PROVIDERS) == set(PROVIDER_RULE_CAPABILITIES)
    for provider, caps in PROVIDER_RULE_CAPABILITIES.items():
        assert caps["rulesPromote"] is True, provider
        assert caps["rulesLoad"] is True, provider
        assert adapter_path_for(provider) == f"providers/{provider}.md"


def test_promote_writes_via_configured_provider_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def writer(root: Path, payload: dict) -> dict:
        captured["root"] = root
        captured["payload"] = payload
        return {
            "verdict": "ok",
            "writtenVia": "configured-provider-adapter",
            "adapterDoc": adapter_path_for("recallium"),
        }

    monkeypatch.setattr(
        "memory_rules_promote.configured_provider",
        lambda root: "recallium",
    )
    monkeypatch.setattr(
        "memory_rules_promote.assert_provider_registered",
        lambda root, provider: {"ok": True, "provider": provider},
    )
    result = promote_rule(
        REPO,
        rule_id="provider-agnostic-rules",
        body=BODY,
        approval=_approval("provider-agnostic-rules", BODY),
        writer=writer,
    )
    assert result["writtenVia"] == "configured-provider-adapter"
    assert result["adapterDoc"] == "providers/recallium.md"
    assert captured["payload"]["ruleId"] == "provider-agnostic-rules"
    assert captured["payload"]["contentHash"] == content_hash(BODY)


def test_promote_refuses_without_audit() -> None:
    with pytest.raises(RuleWriteRefused) as exc:
        promote_rule(
            REPO,
            rule_id="x",
            body=BODY,
            approval={},
            writer=lambda root, payload: {"verdict": "ok"},
        )
    assert exc.value.cause == "rule-write-unapproved"
