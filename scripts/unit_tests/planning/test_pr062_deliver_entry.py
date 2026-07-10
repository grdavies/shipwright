"""PRD 062 phase 1 — issue-store deliver entry (R15 a–c)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from dispatch_intensity_check import parse_anchored_directive
from dispatch_prompt import build_deliver_phase_ship_prompt, INTENSITY_SOURCE_DELIVER_PHASE_SHIP
from planning_deliver_gate import (
    logical_task_list_candidates,
    task_list_path_parts,
    unit_id_from_task_list,
)


@pytest.mark.parametrize(
    ("unit_id", "dir_slug", "task_file"),
    [
        (
            "tasks-061-planning-store-interface-architecture",
            "061-planning-store-interface-architecture",
            "tasks-061-planning-store-interface-architecture.md",
        ),
        (
            "tasks-062-deliver-issue-store-hardening-and-loop-perf",
            "062-deliver-issue-store-hardening-and-loop-perf",
            "tasks-062-deliver-issue-store-hardening-and-loop-perf.md",
        ),
        (
            "tasks-099-demo-with-tasks-in-slug",
            "099-demo-with-tasks-in-slug",
            "tasks-099-demo-with-tasks-in-slug.md",
        ),
    ],
)
def test_task_list_path_parts_strips_leading_tasks_prefix(
    unit_id: str, dir_slug: str, task_file: str
) -> None:
    """R15(b) — store unit ids normalize without double tasks- prefix."""
    assert task_list_path_parts(unit_id) == (dir_slug, task_file)


def test_logical_task_list_candidates_no_double_tasks_prefix(repo_root: Path) -> None:
    """R15(b) — --issue resolution paths use canonical docs/prds/<n>-<slug>/ layout."""
    unit_id = "tasks-061-planning-store-interface-architecture"
    candidates = logical_task_list_candidates(repo_root, unit_id)
    assert candidates
    assert all("tasks-tasks-" not in rel for rel in candidates)
    assert (
        "docs/prds/061-planning-store-interface-architecture/tasks-061-planning-store-interface-architecture.md"
        in candidates
    )


def test_unit_id_from_materialized_path_avoids_double_prd() -> None:
    """R15(b) — materialized paths derive PRD graph unit id, not tasks-tasks- slug."""
    path = Path(
        ".cursor/planning-materialized/docs/prds/062-prd-deliver-issue-store-hardening-and-loop-perf/"
        "tasks-062-deliver-issue-store-hardening-and-loop-perf.md"
    )
    assert unit_id_from_task_list(path) == "062-prd-deliver-issue-store-hardening-and-loop-perf"


def test_build_deliver_phase_ship_prompt_prepends_intensity_directive() -> None:
    """R15(c) — deliver phase-ship prompts include anchored intensity directive (R3)."""
    result = build_deliver_phase_ship_prompt(intensity="normal", body="Run /sw-ship --phase-mode")
    parsed = parse_anchored_directive(result.prompt)
    assert parsed is not None
    intensity, source = parsed
    assert intensity == "normal"
    assert source == INTENSITY_SOURCE_DELIVER_PHASE_SHIP


def test_cmd_provision_materializes_task_list_before_discover() -> None:
    """R15(a) — provision materializes frozen task list before private-spec discover."""
    import inspect
    import planning_materialize as pm

    source = inspect.getsource(pm.cmd_provision)
    discover_idx = source.index("discover_private_spec_units")
    issue_store_block = source.index('if backend_id == "issue-store":')
    assert issue_store_block < discover_idx
    discover_source = inspect.getsource(pm.discover_private_spec_units)
    assert "ensure_run_entry_materialized" in discover_source
    assert "resolve_readable_path" in discover_source
