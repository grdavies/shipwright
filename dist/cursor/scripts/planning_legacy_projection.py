#!/usr/bin/env python3
"""Legacy GAP-BACKLOG/INDEX projections from planning units (PRD 031 R27)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths  # noqa: E402

GAP_ID_RE = re.compile(r"^gap-(\d+)-")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def gap_legacy_id(unit_id: str) -> str:
    m = GAP_ID_RE.match(unit_id)
    if m:
        return f"GAP-{m.group(1)}"
    return unit_id.upper().replace("-", "-")


def render_gap_backlog(units: list[pig.PlanningUnit]) -> str:
    gaps = [u for u in units if u.type == "gap" and u.id != "gap-feedback-checklist"]
    lines = [
        "# Gap backlog (legacy projection)",
        "",
        "Generated compatibility projection from planning gap units (PRD 031 R27).",
        "",
        "| ID | Status | Title |",
        "|----|--------|-------|",
    ]
    for gap in sorted(gaps, key=lambda u: u.id):
        gid = gap_legacy_id(gap.id)
        lines.append(f"| {gid} | {gap.status} | {gap.title} |")
    lines.append("")
    return "\n".join(lines)


def render_prd_index(units: list[pig.PlanningUnit], root: Path) -> str:
    prds = [u for u in units if u.type == "prd"]
    lines = [
        "# PRD index (legacy projection)",
        "",
        "| # | Slug | PRD | Tasks | Status |",
        "|---|------|-----|-------|--------|",
    ]
    for prd in sorted(prds, key=lambda u: u.id):
        m = re.match(r"prd-(\d+)-(.+)", prd.id)
        if not m:
            continue
        num, slug = m.group(1), m.group(2)
        body = Path(prd.body_path).name
        task_path = Path(prd.body_path).parent / f"tasks-{num}-{slug}.md"
        tasks = f"[tasks]({task_path.as_posix()})" if task_path.is_file() else "—"
        lines.append(
            f"| {num} | {slug} | [{body}]({prd.body_path}) | {tasks} | {prd.status} |"
        )
    lines.append("")
    return "\n".join(lines)


def project_all(root: Path, *, dry_run: bool = False) -> dict[str, Any]:
    dirs = planning_paths.load_planning_dirs(root)
    if dirs.planning != "docs/planning":
        return {"skipped": True, "reason": "planningDir not flipped"}
    worktree = planning_paths.git_root(root)
    units = pig.discover_units(root)
    gap_path = worktree / dirs.prds / "GAP-BACKLOG.md"
    index_path = worktree / dirs.prds / "INDEX.md"
    gap_content = render_gap_backlog(units)
    index_content = render_prd_index(units, root)
    if not dry_run:
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(gap_content, encoding="utf-8")
        index_path.write_text(index_content, encoding="utf-8")
    return {
        "gapBacklog": str(gap_path.relative_to(worktree)),
        "index": str(index_path.relative_to(worktree)),
        "gapRows": len([u for u in units if u.type == "gap"]),
        "prdRows": len([u for u in units if u.type == "prd"]),
    }


def cmd_project(root: Path, args: list[str]) -> None:
    dry_run = "--dry-run" in args
    out = project_all(root, dry_run=dry_run)
    if out.get("skipped"):
        emit({"verdict": "pass", "action": "legacy-projection-skip", **out})
    emit({"verdict": "pass", "action": "legacy-projection", "dryRun": dry_run, **out})


def cmd_check_half_migrated(root: Path) -> None:
    dirs = planning_paths.load_planning_dirs(root)
    worktree = planning_paths.git_root(root)
    flipped = dirs.planning == "docs/planning"
    gap = worktree / dirs.prds / "GAP-BACKLOG.md"
    idx = worktree / dirs.prds / "INDEX.md"
    if flipped and (not gap.is_file() or not idx.is_file()):
        fail("half-migrated tree: planningDir flipped but legacy projections missing", exit_code=20)
    emit({"verdict": "pass", "action": "no-half-migrated-check", "planningDir": dirs.planning})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_legacy_projection.py <repo-root> <project|check-half-migrated>")
    root = Path(args[0]).resolve()
    cmd = args[1]
    if cmd == "project":
        cmd_project(root, args[2:])
    elif cmd == "check-half-migrated":
        cmd_check_half_migrated(root)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
