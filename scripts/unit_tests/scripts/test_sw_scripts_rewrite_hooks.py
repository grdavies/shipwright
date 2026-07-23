"""Hook and CI template migration rewriter fixtures (PRD 078 phase 8 / TR3, R3)."""
from __future__ import annotations

from pathlib import Path

from sw_scripts_rewrite import rewrite_text


def test_hook_remediation_string_rewrites_to_bootstrap_argv() -> None:
    body = (
        'remediation=f"python3 scripts/resolve-model-tier.py --agent {agent_id}",\n'
    )
    updated, rewrites = rewrite_text(body)
    assert (
        'remediation=f"python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --agent {agent_id}",'
        in updated
    )
    assert len(rewrites) == 1
    assert rewrites[0].script == "resolve-model-tier.py"


def test_ci_template_consumer_literal_rewrites() -> None:
    body = """\
      - name: Memory preflight
        run: python3 scripts/memory-preflight.py search --scope project
"""
    updated, rewrites = rewrite_text(body)
    assert (
        "python3 scripts/sw_bootstrap.py memory-preflight.py -- search --scope project"
        in updated
    )
    assert len(rewrites) == 1
    assert rewrites[0].script == "memory-preflight.py"


def test_ci_self_repo_only_row_untouched() -> None:
    body = "        run: python3 scripts/test/run_pytest.py scripts/unit_tests/meta/test_gate.py -q\n"
    updated, rewrites = rewrite_text(body)
    assert updated == body
    assert rewrites == []


def test_memory_skill_model_tier_line_rewrites() -> None:
    root = Path(__file__).resolve().parents[3]
    skill = (root / "core" / "skills" / "memory" / "SKILL.md").read_text(encoding="utf-8")
    assert "python3 scripts/sw_bootstrap.py resolve-model-tier.py -- --skill memory" in skill
    assert "python3 scripts/resolve-model-tier.py" not in skill
