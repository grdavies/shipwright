"""PRD 072 R7 — thin AGENTS.md + rule-class standing guidance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from agents_md_thin import audit_agents_md, rule_path, substantive_policy_lines
from shipwright_paths import memory_rule_allowlist_path



def _rule_repo(root: Path, provider: str) -> Path:
    (root / "AGENTS.md").write_bytes((ROOT / "AGENTS.md").read_bytes())
    config = root / ".shipwright/workflow.config.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"memory": {"provider": provider}}))
    allowlist = memory_rule_allowlist_path(root)
    allowlist.parent.mkdir(parents=True, exist_ok=True)
    allowlist.write_text(json.dumps(["mock-realism"]))
    return root


@pytest.fixture
def in_repo_rules(tmp_path: Path) -> Path:
    root = _rule_repo(tmp_path, "in-repo")
    body = rule_path(root, "mock-realism")
    body.parent.mkdir(parents=True)
    body.write_bytes((ROOT / ".cursor/sw-memory/rules/mock-realism.md").read_bytes())
    return root


def test_agents_md_has_no_substantive_standing_policy() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    offenders = substantive_policy_lines(text)
    assert offenders == []


def test_agents_md_rule_pointers_resolve_and_allowlisted(in_repo_rules: Path) -> None:
    live_result = audit_agents_md(ROOT)
    assert live_result["ok"] is True, live_result
    assert "mock-realism" in live_result["ruleIds"]
    result = audit_agents_md(in_repo_rules)
    assert result["ok"] is True, result
    assert "mock-realism" in result["ruleIds"]
    assert rule_path(in_repo_rules, "mock-realism").is_file()


def test_mock_realism_rule_is_rule_class(in_repo_rules: Path) -> None:
    body = rule_path(in_repo_rules, "mock-realism").read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert "category: rule" in body.split("---", 2)[1]
    assert "over_mock_scan" in body


def test_allowlist_contains_mock_realism() -> None:
    data = json.loads(memory_rule_allowlist_path(ROOT).read_text(encoding="utf-8"))
    assert "mock-realism" in data


def test_substantive_policy_detector_flags_legacy_agents_body() -> None:
    legacy = """# Agent guidance

## Mock realism

- Prefer testing against real collaborators when cost is low.
- Avoid mocking the unit under test.

```bash
python3 scripts/over_mock_scan.py --root .
```
"""
    assert substantive_policy_lines(legacy) != []


def test_in_repo_provider_rejects_missing_local_body(in_repo_rules: Path) -> None:
    rule_path(in_repo_rules, "mock-realism").unlink()
    result = audit_agents_md(in_repo_rules)
    assert result["ok"] is False
    assert result["localBodiesRequired"] is True
    assert "missing rule files: mock-realism" in result["errors"]


def test_remote_provider_uses_thin_pointers_without_local_body(tmp_path: Path) -> None:
    root = _rule_repo(tmp_path, "recallium")
    result = audit_agents_md(root)
    assert result["ok"] is True, result
    assert result["provider"] == "recallium"
    assert result["localBodiesRequired"] is False
    assert result["ruleIds"] == ["mock-realism"]
    assert result["dualHomeBodies"] == []
    assert not rule_path(root, "mock-realism").exists()
