#!/usr/bin/env python3
"""Canonical gap unit capture from feedback signals (PRD 033 R15)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig
import planning_paths as pp


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:48] or "feedback-gap"


def next_gap_number(units: list[pig.PlanningUnit]) -> int:
    max_n = 0
    for unit in units:
        m = re.match(r"gap-(\d+)-", unit.id)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def capture_gap(
    root: Path,
    *,
    signal_id: str,
    title: str,
    pr_number: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    dirs = pp.load_planning_dirs(root)
    worktree = pp.git_root(root)
    units = pig.discover_units(root)
    num = next_gap_number(units)
    unit_id = f"gap-{num:03d}-{slugify(title)}"
    unit_dir = worktree / dirs.planning / "gap" / unit_id
    body_path = unit_dir / f"{unit_id}.md"
    fm = [
        "---",
        f"id: {unit_id}",
        "type: gap",
        "status: open",
        f"title: {title}",
        "visibility: public",
        f"tags: [source:feedback, signal:{signal_id}]",
    ]
    if pr_number is not None:
        fm.append(f"source_pr: {pr_number}")
    fm.extend(["---", "", f"# {title}", "", f"_Captured from feedback signal `{signal_id}`._", ""])
    content = "\n".join(fm) + "\n"
    if not dry_run:
        unit_dir.mkdir(parents=True, exist_ok=True)
        body_path.write_text(content, encoding="utf-8")
    return {"unitId": unit_id, "path": str(body_path.relative_to(worktree)), "signalId": signal_id}


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_gap_capture.py <repo-root> capture --signal-id ID --title TITLE [--pr N] [--dry-run]")
    root = Path(args[0]).resolve()
    rest = args[1:]
    if rest[0] != "capture":
        fail(f"unknown command: {rest[0]}")
    signal_id = title = None
    pr_number = None
    dry_run = "--dry-run" in rest
    i = 1
    while i < len(rest):
        if rest[i] == "--signal-id" and i + 1 < len(rest):
            signal_id = rest[i + 1]; i += 2
        elif rest[i] == "--title" and i + 1 < len(rest):
            title = rest[i + 1]; i += 2
        elif rest[i] == "--pr" and i + 1 < len(rest):
            pr_number = int(rest[i + 1]); i += 2
        else:
            i += 1
    if not signal_id or not title:
        fail("--signal-id and --title required")
    out = capture_gap(root, signal_id=signal_id, title=title, pr_number=pr_number, dry_run=dry_run)
    emit({"verdict": "pass", "action": "gap-capture", **out})


if __name__ == "__main__":
    main()
