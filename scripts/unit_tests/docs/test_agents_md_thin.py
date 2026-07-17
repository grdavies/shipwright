"""PRD 072 R7 — thin AGENTS.md + rule-class standing guidance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

from agents_md_thin import audit_agents_md, rule_path, substantive_policy_lines


def test_agents_md_has_no_substantive_standing_policy() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    offenders = substantive_policy_lines(text)
    assert offenders == []


def test_agents_md_rule_pointers_resolve_and_allowlisted() -> None:
    result = audit_agents_md(ROOT)
    assert result["ok"] is True, result
    assert "mock-realism" in result["ruleIds"]
    assert rule_path(ROOT, "mock-realism").is_file()


def test_mock_realism_rule_is_rule_class() -> None:
    body = rule_path(ROOT, "mock-realism").read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert "category: rule" in body.split("---", 2)[1]
    assert "over_mock_scan" in body


def test_allowlist_contains_mock_realism() -> None:
    data = json.loads((ROOT / ".cursor/sw-memory-rule-allowlist.json").read_text(encoding="utf-8"))
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
