"""PRD 277 R5 — hermetic non-in-repo promote then rules-load with no local dual-home."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import rules_load
from memory_rules_promote import content_hash, promote_rule

BODY = "Hermetic fixture rule body.\n"
RULE_ID = "hermetic-rule"


def _approval() -> dict:
    return {
        "command": "sw-memory-audit",
        "ruleId": RULE_ID,
        "contentHash": content_hash(BODY),
        "approvedBy": "operator",
        "provenance": "sw-memory-audit",
    }


def test_hermetic_fixture_promote_load_without_local_dual_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store: dict[str, dict] = {}

    def writer(root: Path, payload: dict) -> dict:
        del root
        store[payload["ruleId"]] = payload
        return {"verdict": "ok", "writtenVia": "hermetic-fixture"}

    def loader(root: Path, provider: str) -> dict:
        del root
        return {
            "ok": True,
            "provider": provider,
            "rules": [
                {"id": rid, "body": item["body"]} for rid, item in store.items()
            ],
        }

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
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": "recallium", "project": "hermetic"}}),
        encoding="utf-8",
    )
    (tmp_path / ".cursor" / "sw-memory-rule-allowlist.json").write_text(
        json.dumps([RULE_ID]),
        encoding="utf-8",
    )

    promoted = promote_rule(
        tmp_path, rule_id=RULE_ID, body=BODY, approval=_approval(), writer=writer
    )
    assert promoted["verdict"] == "ok"
    assert RULE_ID in store
    assert not (tmp_path / ".cursor" / "sw-memory" / "rules" / f"{RULE_ID}.md").is_file()

    loaded = rules_load(tmp_path, loader=loader)
    ids = {entry["id"] for entry in loaded["rules"]}
    assert RULE_ID in ids
    assert loaded["source"] == "rules-load"
