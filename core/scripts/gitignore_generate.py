#!/usr/bin/env python3
"""Visibility-driven .gitignore generator (PRD 034 R13)."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
import planning_paths as pp  # noqa: E402
import planning_visibility as pv  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402

BEGIN_MARKER = "# BEGIN visibility-generated (PRD 034 R13 — scripts/gitignore-generate.py)"
END_MARKER = "# END visibility-generated"

STATIC_TAIL = [
    ".cursor/planning-migration-reverse-map.json",
    ".cursor/planning-migration-gap-id-map.json",
    ".cursor/planning-path-redirect-map.json",
    ".cursor/planning-migration.lock",
    ".cursor/planning-migration-staging/",
    ".cursor/planning-migration-supersession-map.json",
    ".cursor/planning-materialized/",
]

STATIC_HEAD = """# Shipwright local hook state (machine-local, not shared)
.cursor/hooks/state/

# /sw-deliver runtime artifacts (living, per-worktree — not committed)
.cursor/sw-deliver-plan.json
.cursor/sw-deliver-state.json
.cursor/sw-deliver-state.*.json
.cursor/sw-deliver.lock
.cursor/sw-deliver-runs/
.cursor/planning-legacy-projection-stamp.json

# Generated deliver-phase fixture temps (superseded by deliver-phase-mode/tasks/)
scripts/test/fixtures/deliver-phase/

# Python
__pycache__/
*.pyc

# Per-work-item worktrees (local only)
.sw-worktrees/

# Emitter test fixture output (generated locally)
scripts/test/fixtures/emitter-fixture/out/

# Internal planning artifacts: PRDs + guides tracked; bodies resolved per visibility below.
docs/*
!docs/prds/
!docs/prds/**
!docs/guides/
!docs/guides/**
!docs/decisions/
!docs/decisions/**
"""


def emit(obj: dict, exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def strip_generated_section(text: str) -> str:
    if BEGIN_MARKER not in text:
        return text
    pre = text.split(BEGIN_MARKER, 1)[0].rstrip()
    if END_MARKER in text:
        post = text.split(END_MARKER, 1)[1].lstrip("\n")
        if post:
            return pre + "\n\n" + post
    return pre + "\n"


def legacy_planning_privacy_lines() -> list[str]:
    return [
        "# Planning privacy (R18) — brainstorm/decision bodies stay ignored until PRD 034",
        "docs/planning/brainstorm/**/*",
        "!docs/planning/brainstorm/**/.gitkeep",
        "docs/planning/decision/**/*",
        "!docs/planning/decision/INDEX.md",
        "!docs/planning/decision/SUPERSEDED.log",
    ]


def remove_legacy_planning_privacy(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    skip = False
    legacy = set(legacy_planning_privacy_lines())
    for line in lines:
        if line in legacy or line.startswith("# Planning privacy (R18)"):
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def resolved_visibility(unit: pig.PlanningUnit, root: Path) -> str:
    cfg = load_workflow_config(pp.git_root(root))
    fm = pig.unit_frontmatter_dict(unit)
    return pv.resolve_unit_visibility(fm, cfg)["visibility"]


def visibility_section(root: Path) -> str:
    units = pig.discover_units(root)
    cfg = load_workflow_config(pp.git_root(root))
    profile = pv.visibility_profile(cfg)

    ignore_paths: list[str] = []
    track_paths: list[str] = []
    for unit in units:
        vis = resolved_visibility(unit, root)
        rel = unit.body_path.replace("\\", "/")
        if pv.body_is_redacted(vis):
            ignore_paths.append(rel)
        else:
            track_paths.append(rel)

    lines = [
        BEGIN_MARKER,
        f"# profile={profile}; units={len(units)}",
        "# Ignore private/memory unit bodies; un-ignore public bodies under advisory type globs.",
        "docs/planning/brainstorm/**/*",
        "!docs/planning/brainstorm/**/.gitkeep",
        "docs/planning/decision/**/*",
        "!docs/planning/decision/INDEX.md",
        "!docs/planning/decision/SUPERSEDED.log",
        "docs/planning/gap/**/*",
        "docs/planning/amendment/**/*",
    ]
    for rel in sorted(set(track_paths)):
        lines.append(f"!{rel}")
    for rel in sorted(set(ignore_paths)):
        lines.append(rel)
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def render_gitignore(root: Path) -> str:
    path = pp.git_root(root) / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if BEGIN_MARKER in existing:
        base = strip_generated_section(existing)
        base = remove_legacy_planning_privacy(base)
    elif existing.strip():
        base = remove_legacy_planning_privacy(existing)
    else:
        base = STATIC_HEAD.rstrip() + "\n"
        for tail in STATIC_TAIL:
            base += f"\n{tail}"
        base += "\n"
    base = base.rstrip() + "\n\n"
    section = visibility_section(root)
    text = base + section
    if not text.endswith("\n"):
        text += "\n"
    return text


def git_tracked_paths(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def verify_index(root: Path) -> dict:
    worktree = pp.git_root(root)
    units = pig.discover_units(root)
    by_path = {u.body_path.replace("\\", "/"): u for u in units}
    violations: list[dict[str, str]] = []
    for rel in git_tracked_paths(worktree):
        unit = by_path.get(rel)
        if unit is None:
            continue
        vis = resolved_visibility(unit, worktree)
        if pv.body_is_redacted(vis):
            violations.append({"path": rel, "visibility": vis, "unitId": unit.id})
    if violations:
        return {"verdict": "fail", "error": "private-body-bytes-in-index", "violations": violations}
    return {"verdict": "pass", "action": "verify-index", "checkedUnits": len(units)}


def cmd_generate(root: Path, write: bool) -> int:
    text = render_gitignore(root)
    if write:
        out_path = pp.git_root(root) / ".gitignore"
        out_path.write_text(text, encoding="utf-8")
        emit({"verdict": "pass", "action": "generate", "path": str(out_path.relative_to(pp.git_root(root)))})
    sys.stdout.write(text)
    return 0


def cmd_verify_index(root: Path) -> int:
    result = verify_index(root)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "pass" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Visibility-driven .gitignore generator (PRD 034 R13)")
    parser.add_argument("--root", default=".", help="Repository root")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Render .gitignore from visibility resolver")
    gen.add_argument("--write", action="store_true", help="Write .gitignore in repo root")
    gen.set_defaults(func=lambda a: cmd_generate(Path(a.root), a.write))

    verify = sub.add_parser("verify-index", help="Assert zero private/memory unit bodies in git index")
    verify.set_defaults(func=lambda a: cmd_verify_index(Path(a.root)))

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
