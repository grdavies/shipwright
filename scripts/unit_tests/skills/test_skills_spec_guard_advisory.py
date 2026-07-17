"""PRD 072 R9 — skills_spec_guard soft line-budget advisory + dist parity."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from skills_spec_guard import (
    ADVISORY_SKILL_LINES,
    MAX_SKILL_LINES,
    check_repo,
    scan_tree,
)


def _skill_md(name: str, body_lines: int) -> str:
    return (
        "---\n"
        f"name: {name}\n"
        'description: Fixture skill for line-budget tests. Use when validating advisory thresholds in skills_spec_guard.\n'
        "---\n"
        "# fixture\n"
        + "\n".join(f"line {i}" for i in range(1, body_lines + 1))
        + "\n"
    )


def _write_skill(repo_root: Path, tree: str, name: str, total_lines: int) -> Path:
    skill_dir = repo_root / tree / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    body_lines = max(0, total_lines - 5)
    path = skill_dir / "SKILL.md"
    path.write_text(_skill_md(name, body_lines), encoding="utf-8")
    return path


def test_advisory_threshold_constants() -> None:
    assert ADVISORY_SKILL_LINES == 450
    assert MAX_SKILL_LINES == 500


def test_skill_at_advisory_threshold_passes_with_advisory(tmp_path: Path) -> None:
    _write_skill(tmp_path, "core/skills", "advisory-skill", ADVISORY_SKILL_LINES)
    result = check_repo(tmp_path, tree_prefixes=("core/skills",))
    assert result["verdict"] == "pass"
    assert result.get("advisoryCount", 0) == 1
    codes = {item["code"] for item in result.get("advisories", [])}
    assert "skill-line-budget-advisory" in codes


def test_skill_below_advisory_has_no_advisory(tmp_path: Path) -> None:
    _write_skill(tmp_path, "core/skills", "short-skill", ADVISORY_SKILL_LINES - 1)
    result = check_repo(tmp_path, tree_prefixes=("core/skills",))
    assert result["verdict"] == "pass"
    assert result.get("advisoryCount", 0) == 0
    assert result.get("advisories", []) == []


def test_skill_over_hard_limit_fails(tmp_path: Path) -> None:
    _write_skill(tmp_path, "core/skills", "too-long-skill", MAX_SKILL_LINES + 1)
    result = check_repo(tmp_path, tree_prefixes=("core/skills",))
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result.get("findings", [])}
    assert "skill-line-budget" in codes


def _skill_body(text: str) -> str:
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4 :].lstrip("\n")


def test_conductor_skill_line_budget_and_dist_parity(repo_root: Path) -> None:
    core = repo_root / "core/skills/conductor/SKILL.md"
    assert core.is_file(), "core conductor SKILL.md missing"
    core_text = core.read_text(encoding="utf-8")
    core_lines = len(core_text.splitlines())
    assert core_lines <= ADVISORY_SKILL_LINES, (
        f"conductor SKILL.md has {core_lines} lines (target ~400, max advisory {ADVISORY_SKILL_LINES})"
    )

    cursor = repo_root / "dist/cursor/skills/conductor/SKILL.md"
    claude = repo_root / "dist/claude-code/skills/conductor/SKILL.md"
    assert cursor.is_file(), "missing dist/cursor conductor mirror"
    assert claude.is_file(), "missing dist/claude-code conductor mirror"
    assert cursor.read_text(encoding="utf-8") == core_text

    cursor_body = _skill_body(cursor.read_text(encoding="utf-8"))
    claude_body = _skill_body(claude.read_text(encoding="utf-8"))
    assert cursor_body == claude_body

    refs = sorted((core.parent / "references").glob("*.md"))
    assert refs, "expected carved conductor references"
    for ref in refs:
        rel = ref.relative_to(core.parent)
        for tree in ("dist/cursor/skills/conductor", "dist/claude-code/skills/conductor"):
            mirror_ref = repo_root / tree / rel
            assert mirror_ref.is_file(), f"missing mirror {mirror_ref}"
            assert mirror_ref.read_text(encoding="utf-8") == ref.read_text(encoding="utf-8")


def test_scan_tree_separates_advisories_from_findings(tmp_path: Path) -> None:
    _write_skill(tmp_path, "core/skills", "warn-skill", 460)
    findings = scan_tree(tmp_path, "core/skills")
    hard = [f for f in findings if f.code == "skill-line-budget"]
    advisory = [f for f in findings if f.code == "skill-line-budget-advisory"]
    assert not hard
    assert len(advisory) == 1
