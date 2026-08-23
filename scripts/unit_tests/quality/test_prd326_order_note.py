"""PRD 326 R20 — delivery order note matches frozen task-list Phase Dependencies."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "core" / "sw-reference" / "README.md"
TASKS_ARTIFACT = (
    REPO_ROOT
    / ".cursor"
    / "planning-materialized"
    / "docs"
    / "prds"
    / "326-workflow-quality-platform"
    / "tasks-326-workflow-quality-platform.md"
)

# Canonical phase edges from frozen tasks-326-workflow-quality-platform.md (issue-store).
PRD_326_PHASE_DEPS: dict[str, frozenset[str]] = {
    "1": frozenset(),
    "2": frozenset({"1"}),
    "3": frozenset({"1"}),
    "4": frozenset({"1"}),
    "5": frozenset({"1"}),
    "6": frozenset({"5"}),
    "7": frozenset({"6"}),
    "8": frozenset({"7"}),
    "9": frozenset({"1"}),
    "10": frozenset({"9"}),
    "11": frozenset({"1"}),
    "12": frozenset({"1"}),
    "13": frozenset({"2", "3", "4", "8", "10", "11", "12"}),
}

PRD_326_ORDER_NOTE_SECTION = "## PRD 326 delivery order (R20)"


def _parse_phase_dependencies_table(content: str) -> dict[str, frozenset[str]]:
    match = re.search(r"^## Phase Dependencies\s*$", content, flags=re.MULTILINE)
    if not match:
        raise AssertionError("missing ## Phase Dependencies section")
    section = content[match.end() :]
    rows: dict[str, frozenset[str]] = {}
    for line in section.splitlines():
        if not line.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 2 or cells[0] == "Phase" or cells[0].startswith("---"):
            continue
        phase, depends = cells
        if depends.lower() == "none":
            deps: frozenset[str] = frozenset()
        else:
            deps = frozenset(part.strip() for part in depends.split(",") if part.strip())
        rows[phase] = deps
    if not rows:
        raise AssertionError("Phase Dependencies table has no data rows")
    return rows


def _extract_prd326_note_section(readme: str) -> str:
    start = readme.find(PRD_326_ORDER_NOTE_SECTION)
    if start < 0:
        raise AssertionError(f"missing {PRD_326_ORDER_NOTE_SECTION!r} in core/sw-reference/README.md")
    rest = readme[start + len(PRD_326_ORDER_NOTE_SECTION) :]
    next_heading = re.search(r"\n## [^#]", rest)
    return rest[: next_heading.start()] if next_heading else rest


def test_prd326_order_note_exists_and_documents_constraints() -> None:
    readme = README.read_text(encoding="utf-8")
    note = _extract_prd326_note_section(readme)
    lowered = note.lower()
    assert "phase 1" in lowered and "residual hardening" in lowered
    assert "5" in note and "6" in note and "7" in note and "8" in note
    assert "9" in note and "10" in note
    assert "phase 13" in lowered or "absorb closeout" in lowered
    assert "terminal" in lowered
    for phase in ("2", "3", "4", "8", "10", "11", "12"):
        assert phase in note


def test_prd326_readme_phase_dependencies_match_canonical() -> None:
    readme = README.read_text(encoding="utf-8")
    readme_deps = _parse_phase_dependencies_table(readme)
    assert readme_deps == PRD_326_PHASE_DEPS


def test_prd326_order_note_and_readme_phase_deps_are_consistent() -> None:
    readme = README.read_text(encoding="utf-8")
    _extract_prd326_note_section(readme)
    readme_deps = _parse_phase_dependencies_table(readme)
    assert readme_deps == PRD_326_PHASE_DEPS


@pytest.mark.skipif(not TASKS_ARTIFACT.is_file(), reason="materialized task list not present")
def test_task_list_phase_dependencies_match_canonical() -> None:
    tasks = TASKS_ARTIFACT.read_text(encoding="utf-8")
    parsed = _parse_phase_dependencies_table(tasks)
    assert parsed == PRD_326_PHASE_DEPS
