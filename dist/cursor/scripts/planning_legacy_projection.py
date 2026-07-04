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
import planning_visibility as pv  # noqa: E402
import gap_backlog as gb  # noqa: E402

LEGACY_GENERATED_MARKER = "<!-- planning-legacy-projection: generated v1 -->"



def redacted_title(unit: pig.PlanningUnit, root: Path) -> str:
    row = pig.index_row_dict(unit, root)
    return str(row.get("title", unit.title))

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


def render_gap_backlog(units: list[pig.PlanningUnit], root: Path) -> str:
    gaps = [u for u in units if u.type == "gap" and u.id != "gap-feedback-checklist"]
    lines = [
        LEGACY_GENERATED_MARKER,
        "",
        "Generated compatibility projection from planning gap units (PRD 031 R27).",
        "",
        "| ID | Status | Title |",
        "|----|--------|-------|",
    ]
    for gap in sorted(gaps, key=lambda u: u.id):
        gid = gap_legacy_id(gap.id)
        lines.append(f"| {gid} | {gap.status} | {redacted_title(gap, root)} |")
    lines.append("")
    return "\n".join(lines)


def render_prd_index(units: list[pig.PlanningUnit], root: Path) -> str:
    prds = [u for u in units if u.type == "prd"]
    lines = [
        LEGACY_GENERATED_MARKER,
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
        title = redacted_title(prd, root)
        lines.append(
            f"| {num} | {slug} | [{title}]({prd.body_path}) | {tasks} | {prd.status} |"
        )
    lines.append("")
    return "\n".join(lines)



def unit_body_sentinels(root: Path, units: list[pig.PlanningUnit]) -> list[str]:
    """Unique body substrings used to prove projections are frontmatter-only (R15)."""
    worktree = planning_paths.git_root(root)
    sentinels: list[str] = []
    for unit in units:
        body = worktree / unit.body_path
        if not body.is_file():
            continue
        raw = body.read_text(encoding="utf-8")
        if raw.startswith("---"):
            parts = raw.split("---", 2)
            body_text = parts[2] if len(parts) > 2 else ""
        else:
            body_text = raw
        for line in body_text.splitlines():
            line = line.strip()
            if len(line) >= 12 and not line.startswith("#"):
                sentinels.append(line)
                break
    return sentinels


def verify_frontmatter_only(root: Path, gap_content: str, index_content: str, units: list[pig.PlanningUnit]) -> list[str]:
    leaks: list[str] = []
    for sentinel in unit_body_sentinels(root, units):
        if sentinel in gap_content or sentinel in index_content:
            leaks.append(sentinel)
    return leaks


def write_legacy_stamp(root: Path, *, gap_hash: str, index_hash: str) -> None:
    worktree = planning_paths.git_root(root)
    stamp = worktree / ".cursor" / "planning-legacy-projection-stamp.json"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    import hashlib, json
    stamp.write_text(json.dumps({"gapBacklogSha256": gap_hash, "indexSha256": index_hash}, indent=2) + "\n", encoding="utf-8")


def legacy_manual_edit_warnings(root: Path) -> list[dict[str, str]]:
    import hashlib, json
    dirs = planning_paths.load_planning_dirs(root)
    if dirs.planning != "docs/planning":
        return []
    worktree = planning_paths.git_root(root)
    stamp_path = worktree / ".cursor" / "planning-legacy-projection-stamp.json"
    if not stamp_path.is_file():
        return []
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    warnings: list[dict[str, str]] = []
    for key, rel_name in (("gapBacklogSha256", "GAP-BACKLOG.md"), ("indexSha256", "INDEX.md")):
        expected = stamp.get(key)
        path = worktree / dirs.prds / rel_name
        if not expected or not path.is_file():
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            warnings.append({
                "check": "legacy-manual-edit",
                "path": str(path.relative_to(worktree)),
                "hint": "legacy projection is read-only; edit canonical planning units and reconcile",
            })
    return warnings



def migration_gate_blocks_cutover(root: Path) -> dict[str, Any]:
    dirs = planning_paths.load_planning_dirs(root)
    worktree = planning_paths.git_root(root)
    gap_path = worktree / dirs.prds / "GAP-BACKLOG.md"
    if not gap_path.is_file():
        return {"blocked": False, "reason": "no-legacy-backlog"}
    content = gap_path.read_text(encoding="utf-8")
    if LEGACY_GENERATED_MARKER in content:
        return {"blocked": False, "reason": "already-generated"}
    gate = gb.migration_gate_check(root)
    return {"blocked": gate.get("verdict") != "pass", **gate}


def cmd_projection_cutover_ready(root: Path) -> None:
    gate = migration_gate_blocks_cutover(root)
    if gate.get("blocked"):
        fail(
            "projection cutover blocked: unresolved legacy backlog rows",
            exit_code=20,
            halt="migration-gate",
            **{k: v for k, v in gate.items() if k != "blocked"},
        )
    emit({"verdict": "pass", "action": "projection-cutover-ready"})

def hand_maintained_legacy_paths(worktree: Path, dirs: Any) -> list[str]:
    """Paths missing generated marker — refuse wipe without --force (R48)."""
    hand: list[str] = []
    for name in ("GAP-BACKLOG.md", "INDEX.md"):
        path = worktree / dirs.prds / name
        if path.is_file():
            content = path.read_text(encoding="utf-8")
            if LEGACY_GENERATED_MARKER not in content:
                hand.append(str(path.relative_to(worktree)))
    return hand


def project_all(root: Path, *, dry_run: bool = False, force: bool = False) -> dict[str, Any]:
    dirs = planning_paths.load_planning_dirs(root)
    if dirs.planning != "docs/planning":
        return {"skipped": True, "reason": "planningDir not flipped"}
    worktree = planning_paths.git_root(root)
    units = pig.discover_units(root)
    hand = hand_maintained_legacy_paths(worktree, dirs)
    gate = migration_gate_blocks_cutover(root)
    if gate.get("blocked") and not force and not dry_run:
        fail(
            "migration gate blocks projection cutover",
            exit_code=20,
            halt="migration-gate",
            unresolved=gate.get("unresolved", []),
            unresolvedCount=gate.get("unresolvedCount", 0),
            remediation="resolve or map legacy rows before cutover",
        )
    if hand and not force and not dry_run:
        fail(
            "refuse to overwrite hand-maintained legacy projection",
            exit_code=20,
            halt="projection-refuse",
            paths=hand,
            remediation="pass --force after human review",
        )
    gap_path = worktree / dirs.prds / "GAP-BACKLOG.md"
    index_path = worktree / dirs.prds / "INDEX.md"
    gap_content = render_gap_backlog(units, root)
    index_content = render_prd_index(units, root)
    leaks = verify_frontmatter_only(root, gap_content, index_content, units)
    if leaks:
        fail("legacy projection leaked unit body bytes", leaks=leaks, exit_code=20)
    if not dry_run:
        gap_path.parent.mkdir(parents=True, exist_ok=True)
        gap_path.write_text(gap_content, encoding="utf-8")
        index_path.write_text(index_content, encoding="utf-8")
        import hashlib
        write_legacy_stamp(
            root,
            gap_hash=hashlib.sha256(gap_content.encode()).hexdigest(),
            index_hash=hashlib.sha256(index_content.encode()).hexdigest(),
        )
    return {
        "gapBacklog": str(gap_path.relative_to(worktree)),
        "index": str(index_path.relative_to(worktree)),
        "gapRows": len([u for u in units if u.type == "gap"]),
        "prdRows": len([u for u in units if u.type == "prd"]),
    }


def cmd_project(root: Path, args: list[str]) -> None:
    dry_run = "--dry-run" in args
    force = "--force" in args
    out = project_all(root, dry_run=dry_run, force=force)
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
        fail("usage: planning_legacy_projection.py <repo-root> <project|check-half-migrated|verify-frontmatter-only|projection-cutover-ready>")
    root = Path(args[0]).resolve()
    cmd = args[1]
    if cmd == "project":
        cmd_project(root, args[2:])
    elif cmd == "verify-frontmatter-only":
        units = pig.discover_units(root)
        out = project_all(root, dry_run=True)
        if out.get("skipped"):
            emit({"verdict": "pass", "action": "verify-frontmatter-only", "skipped": True})
        dirs = planning_paths.load_planning_dirs(root)
        worktree = planning_paths.git_root(root)
        gap_content = (worktree / dirs.prds / "GAP-BACKLOG.md").read_text(encoding="utf-8")
        index_content = (worktree / dirs.prds / "INDEX.md").read_text(encoding="utf-8")
        leaks = verify_frontmatter_only(root, gap_content, index_content, units)
        if leaks:
            fail("body bytes in legacy projection", leaks=leaks, exit_code=20)
        emit({"verdict": "pass", "action": "verify-frontmatter-only"})
    elif cmd == "check-half-migrated":
        cmd_check_half_migrated(root)
    elif cmd == "projection-cutover-ready":
        cmd_projection_cutover_ready(root)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
