"""PRD 277 R2/R4 — thin-pointer audits pass without dual-homed local bodies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from agents_md_thin import audit_agents_md, local_rule_bodies_required, rule_path

AGENTS = """# Agent guidance

Standing guidance is rule-class memory. Pointers only.

| Topic | Rule id | Path |
| --- | --- | --- |
| Thin | `thin-rule` | adapter rules-load |
"""


def _write_fixture(root: Path, *, provider: str) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps({"memory": {"provider": provider, "project": "fixture"}}),
        encoding="utf-8",
    )
    (cursor / "sw-memory-rule-allowlist.json").write_text(
        json.dumps(["thin-rule"]) + "\n",
        encoding="utf-8",
    )
    (root / "AGENTS.md").write_text(AGENTS, encoding="utf-8")


def test_non_in_repo_does_not_require_local_bodies() -> None:
    assert local_rule_bodies_required("recallium") is False
    assert local_rule_bodies_required("in-repo") is True


def test_thin_pointer_allowlist_audit_without_dual_home(tmp_path: Path) -> None:
    _write_fixture(tmp_path, provider="recallium")
    assert not rule_path(tmp_path, "thin-rule").is_file()
    result = audit_agents_md(tmp_path)
    assert result["ok"] is True, result
    assert result["provider"] == "recallium"
    assert result["localBodiesRequired"] is False
    assert "thin-rule" in result["ruleIds"]
    assert result["dualHomeBodies"] == []
