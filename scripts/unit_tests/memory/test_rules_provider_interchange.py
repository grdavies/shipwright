"""PRD 277 R8/R9 + D1–D7 — interchangeable promote+load and decision-ack docs."""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import rules_load
from memory_rules_promote import (
    AUDIT_COMMAND,
    adapter_path_for,
    content_hash,
    promote_rule,
)

REPO = SCRIPTS.parent
BODY = "Interchange rule body — provider-agnostic promote and load.\n"
RULE_ID = "interchange-rule"

ADAPTER_DOCS = (
    "core/providers/in-repo.md",
    "core/providers/recallium.md",
    "core/providers/mempalace.md",
    "core/providers/basic-memory.md",
    "core/providers/obsidian.md",
)


def _approval() -> dict:
    return {
        "command": AUDIT_COMMAND,
        "ruleId": RULE_ID,
        "contentHash": content_hash(BODY),
        "approvedBy": "operator",
        "approvedAt": "2026-08-18T00:00:00Z",
        "provenance": "sw-memory-audit",
    }


def _wire_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": provider, "project": "interchange"}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "memory_rules_promote.assert_provider_registered",
        lambda root, configured: {"ok": True, "provider": configured},
    )
    monkeypatch.setattr(
        "memory_preflight.validate_registration",
        lambda root, configured: {"ok": True, "provider": configured},
    )


def _promote_and_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> dict:
    _wire_provider(tmp_path, monkeypatch, provider)
    store: dict[str, dict] = {}

    def writer(root: Path, payload: dict) -> dict:
        store[payload["ruleId"]] = dict(payload)
        if provider == "in-repo":
            rules_dir = root / ".cursor" / "sw-memory" / "rules"
            rules_dir.mkdir(parents=True, exist_ok=True)
            (rules_dir / f"{payload['ruleId']}.md").write_text(payload["body"], encoding="utf-8")
        return {
            "verdict": "ok",
            "writtenVia": "configured-provider-adapter",
            "adapterDoc": adapter_path_for(provider),
        }

    def loader(root: Path, loaded_provider: str) -> dict:
        del root
        return {
            "ok": True,
            "provider": loaded_provider,
            "rules": [{"id": rid, "body": item["body"]} for rid, item in store.items()],
        }

    promoted = promote_rule(
        tmp_path,
        rule_id=RULE_ID,
        body=BODY,
        approval=_approval(),
        writer=writer,
    )
    loaded = rules_load(tmp_path, loader=loader)
    local_body = tmp_path / ".cursor" / "sw-memory" / "rules" / f"{RULE_ID}.md"
    return {
        "provider": provider,
        "promoted": promoted,
        "loaded": loaded,
        "store": store,
        "localBody": local_body.is_file(),
    }


def test_interchangeable_promote_load_in_repo_and_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    promote_src = inspect.getsource(promote_rule)
    load_src = inspect.getsource(rules_load)
    assert "sw-memory-sync" not in promote_src
    assert "sw-memory-import" not in promote_src
    assert "sw-memory-sync" not in load_src
    assert "sw-memory-import" not in load_src
    assert AUDIT_COMMAND == "sw-memory-audit"

    outcomes: dict[str, dict] = {}
    for provider in ("in-repo", "recallium"):
        root = tmp_path / provider
        root.mkdir()
        outcomes[provider] = _promote_and_load(root, monkeypatch, provider)

    in_repo = outcomes["in-repo"]
    fixture = outcomes["recallium"]
    for outcome in (in_repo, fixture):
        assert outcome["promoted"]["verdict"] == "ok"
        assert outcome["promoted"]["adapterDoc"] == adapter_path_for(outcome["provider"])
        assert RULE_ID in outcome["promoted"]["allowlist"]
        assert RULE_ID in outcome["store"]
        assert outcome["loaded"]["source"] == "rules-load"
        assert outcome["loaded"]["op"] == "rules-load"
        ids = {entry["id"] for entry in outcome["loaded"]["rules"]}
        assert RULE_ID in ids

    assert in_repo["localBody"] is True
    assert fixture["localBody"] is False
    assert in_repo["promoted"]["adapterDoc"] != fixture["promoted"]["adapterDoc"]


def test_docs_memory_capabilities_and_adapters_updated() -> None:
    capabilities = (REPO / "core/skills/memory/CAPABILITIES.md").read_text(encoding="utf-8")
    assert "Provider-aware rule promote and load" in capabilities
    assert "rulesPromote" in capabilities
    assert "rulesLoad" in capabilities
    assert "rulesRevoke" in capabilities
    assert "/sw-memory-audit" in capabilities
    assert "providers/<" in capabilities or "providers/<memory.provider>.md" in capabilities
    assert "maintain-derived" in capabilities

    for rel in ADAPTER_DOCS:
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "PRD 277" in text, rel
        assert "/sw-memory-audit" in text, rel
        assert "rules-load" in text, rel


def test_decision_provider_agnostic() -> None:
    audit = (REPO / "core/commands/sw-memory-audit.md").read_text(encoding="utf-8")
    assert "D1" in audit
    assert "provider-agnostic" in audit.lower()
    assert "/sw-memory-audit" in audit
    assert "memory.provider" in audit or "providers/" in audit


def test_decision_no_dual_home_unless_in_repo() -> None:
    audit = (REPO / "core/commands/sw-memory-audit.md").read_text(encoding="utf-8")
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "D2" in audit
    assert "dual-home" in audit.lower() or "dual home" in audit.lower()
    assert "in-repo" in audit
    assert "thin" in agents.lower() or "pointer" in agents.lower()
    assert "in-repo" in agents
    assert "dual-home" in agents.lower() or "dual home" in agents.lower()


def test_decision_human_gated_promotion() -> None:
    guardrails = (REPO / "core/rules/memory-guardrails.mdc").read_text(encoding="utf-8")
    assert "D3" in guardrails
    assert "human-gated" in guardrails.lower() or "human gated" in guardrails.lower()
    assert "/sw-memory-audit" in guardrails
    assert "allowlist" in guardrails.lower()


def test_decision_planning_store_issue_numbers() -> None:
    guardrails = (REPO / "core/rules/memory-guardrails.mdc").read_text(encoding="utf-8")
    assert "D4" in guardrails
    assert "planningIssues" in guardrails
    assert "planning-store" in guardrails


def test_decision_needs_reconcile_partial_failure() -> None:
    skill = (REPO / "core/skills/memory/SKILL.md").read_text(encoding="utf-8")
    assert "D5" in skill
    assert "needs-reconcile" in skill
    assert "allowlist" in skill.lower()


def test_decision_integrity_id_hash() -> None:
    skill = (REPO / "core/skills/memory/SKILL.md").read_text(encoding="utf-8")
    assert "D6" in skill
    assert "contentHash" in skill or "content hash" in skill.lower()
    assert "ruleId" in skill or "rule id" in skill.lower()


def test_decision_revocation_both_sides() -> None:
    config = (REPO / "docs/guides/configuration.md").read_text(encoding="utf-8")
    assert "D7" in config
    assert "allowlist" in config.lower()
    assert "inactivate" in config.lower() or "revoke" in config.lower()
    assert "cache" in config.lower()
