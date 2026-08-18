"""PRD 277 R12 — revoke drops allowlist, provider copy, and cache."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from memory_preflight import rules_load
from memory_rules_promote import (
    IN_REPO_RULES_REL,
    content_hash,
    promote_rule,
    revoke_rule,
)

BODY = "Revoke fixture.\n"
RULE_ID = "revoke-rule"


def test_revoke_allowlist_and_provider_no_stale_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("memory_rules_promote.configured_provider", lambda root: "in-repo")
    monkeypatch.setattr(
        "memory_rules_promote.assert_provider_registered",
        lambda root, provider: {"ok": True, "provider": provider},
    )
    monkeypatch.setattr("memory_preflight.configured_provider", lambda root: "in-repo")
    monkeypatch.setattr(
        "memory_preflight.validate_registration",
        lambda root, provider: {"ok": True, "provider": provider},
    )
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": "in-repo", "project": "t"}}),
        encoding="utf-8",
    )
    rules_dir = tmp_path / IN_REPO_RULES_REL
    rules_dir.mkdir(parents=True)
    (rules_dir / f"{RULE_ID}.md").write_text(BODY, encoding="utf-8")

    promoted = promote_rule(
        tmp_path,
        rule_id=RULE_ID,
        body=BODY,
        approval={
            "command": "sw-memory-audit",
            "ruleId": RULE_ID,
            "contentHash": content_hash(BODY),
            "approvedBy": "operator",
            "provenance": "sw-memory-audit",
        },
        writer=lambda root, payload: {"verdict": "ok", "writtenVia": "in-repo-adapter"},
    )
    assert RULE_ID in promoted["allowlist"]

    revoked = revoke_rule(tmp_path, RULE_ID)
    assert RULE_ID not in revoked["allowlist"]
    assert RULE_ID in revoked["revoked"]
    assert RULE_ID not in revoked["cache"]
    assert not (rules_dir / f"{RULE_ID}.md").is_file()
    assert (rules_dir / f"{RULE_ID}.md.deleted").is_file()

    loaded = rules_load(
        tmp_path,
        loader=lambda root, provider: {
            "rules": [{"id": RULE_ID, "body": BODY}, {"id": "other", "body": "x"}]
        },
    )
    ids = {entry.get("id") for entry in loaded["rules"]}
    assert RULE_ID not in ids
