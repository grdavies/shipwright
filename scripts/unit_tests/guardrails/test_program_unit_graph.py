"""Assert tasks phase edges match the R7 program unit graph (PRD 342 R7)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

TASKS_CANDIDATES = (
    REPO_ROOT
    / ".cursor"
    / "planning-materialized"
    / "docs"
    / "prds"
    / "342-spec-kit-learnings"
    / "tasks-342-spec-kit-learnings.md",
    REPO_ROOT
    / "docs"
    / "prds"
    / "342-spec-kit-learnings"
    / "tasks-342-spec-kit-learnings.md",
)

# Phases 1–4 → unit 1; 5–6 → unit 2; 7–8 → unit 3; 9–10 → unit 4;
# phase 11 → unit 5; phases 12–13 → unit 6.
PHASE_TO_UNIT: dict[int, int] = {
    1: 1,
    2: 1,
    3: 1,
    4: 1,
    5: 2,
    6: 2,
    7: 3,
    8: 3,
    9: 4,
    10: 4,
    11: 5,
    12: 6,
    13: 6,
}


def _tasks_path() -> Path:
    for candidate in TASKS_CANDIDATES:
        if candidate.is_file():
            return candidate
    pytest.skip("tasks-342-spec-kit-learnings.md not materialized in this worktree")


def _parse_phase_deps(text: str) -> dict[int, set[int]]:
    match = re.search(r"## Phase Dependencies\s*\n+(?:\|[^\n]+\n)+", text)
    if not match:
        raise AssertionError("Phase Dependencies table not found")
    deps: dict[int, set[int]] = {}
    for line in match.group(0).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0].lower() == "phase" or set(cells[0]) <= {"-", ":"}:
            continue
        try:
            phase = int(cells[0])
        except ValueError:
            continue
        raw = cells[1].lower()
        if raw in {"none", "", "—", "-"}:
            deps[phase] = set()
            continue
        preds: set[int] = set()
        for part in re.split(r"[,\s]+", raw):
            if part:
                preds.add(int(part))
        deps[phase] = preds
    return deps


def _unit_preds_direct(phase_deps: dict[int, set[int]]) -> dict[int, set[int]]:
    unit_preds: dict[int, set[int]] = {u: set() for u in set(PHASE_TO_UNIT.values())}
    for phase, preds in phase_deps.items():
        unit = PHASE_TO_UNIT[phase]
        for pred in preds:
            pred_unit = PHASE_TO_UNIT[pred]
            if pred_unit != unit:
                unit_preds[unit].add(pred_unit)
    return unit_preds


def _reaches(
    unit: int,
    target: int,
    unit_preds: dict[int, set[int]],
    seen: set[int] | None = None,
) -> bool:
    if unit == target:
        return True
    seen = set() if seen is None else seen
    if unit in seen:
        return False
    seen = seen | {unit}
    return any(_reaches(pred, target, unit_preds, seen) for pred in unit_preds.get(unit, ()))


def test_phase_edges_match_r7_unit_graph() -> None:
    text = _tasks_path().read_text(encoding="utf-8")
    phase_deps = _parse_phase_deps(text)
    assert set(phase_deps) == set(PHASE_TO_UNIT)

    # Unit 1 phases never depend on another unit.
    for phase, unit in PHASE_TO_UNIT.items():
        if unit != 1:
            continue
        for pred in phase_deps[phase]:
            assert PHASE_TO_UNIT[pred] == 1

    unit_preds = _unit_preds_direct(phase_deps)

    # Unit 1 precedes every other unit (transitively via the phase/unit graph).
    for unit in (2, 3, 4, 5, 6):
        assert _reaches(unit, 1, unit_preds), f"unit {unit} does not reach unit 1"

    # Unit 4 depends on unit 1 only.
    assert unit_preds[4] == {1}, f"unit 4 preds={unit_preds[4]}"
    assert phase_deps[9] == {4}

    # Units 5 and 6 follow unit 4.
    assert 4 in unit_preds[5]
    assert 4 in unit_preds[6]
    assert phase_deps[11] == {10}
    assert phase_deps[12] == {10}

    # No contradictory edges: unit 4 must not depend on 2 or 3.
    assert 2 not in unit_preds[4] and 3 not in unit_preds[4]
