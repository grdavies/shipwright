#!/usr/bin/env python3
"""Planning corpus migration tool — dry-run/write/verify/rollback (PRD 031 R6/R8/R20/R21/R29/R32)."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths  # noqa: E402
import planning_path_redirect  # noqa: E402

LOCK_REL = ".cursor/planning-migration.lock"
STAGING_REL = ".cursor/planning-migration-staging"
REVERSE_MAP_REL = ".cursor/planning-migration-reverse-map.json"
GAP_MAP_REL = ".cursor/planning-migration-gap-id-map.json"
REDIRECT_MAP_REL = planning_path_redirect.REDIRECT_MAP_REL
FEEDBACK_CHECKLIST_REL = "docs/prds/FEEDBACK-CHECKLIST.md"

ALLOWED_TOUCH_PREFIXES = (
    "docs/",
    ".cursor/workflow.config.json",
    "workflow.config.json",
    ".gitignore",
)

LIVING_DOC_NAMES = ("INDEX.md", "COMPLETION-LOG.md", "GAP-BACKLOG.md")


@dataclass
class Relocation:
    src: str
    dst: str
    kind: str
    body_hash: str | None = None
    gap_id: str | None = None
    gap_status: str | None = None
    gap_title: str | None = None
    source_body: str | None = None


@dataclass
class MigrationPlan:
    relocations: list[Relocation] = field(default_factory=list)
    gap_id_map: dict[str, str] = field(default_factory=dict)
    feedback_items: list[str] = field(default_factory=list)
    config_flip: dict[str, str] = field(default_factory=dict)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def git_root(root: Path) -> Path:
    return planning_paths.git_root(root)


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(git_root(root))).replace("\\", "/")


def sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lock_path(root: Path) -> Path:
    return git_root(root) / LOCK_REL


def staging_path(root: Path) -> Path:
    return git_root(root) / STAGING_REL


def reverse_map_path(root: Path) -> Path:
    return git_root(root) / REVERSE_MAP_REL


def gap_map_path(root: Path) -> Path:
    return git_root(root) / GAP_MAP_REL


def is_private_source(root: Path, src_rel: str) -> bool:
    """Paths that were gitignored pre-migration (brainstorms, decision bodies)."""
    norm = src_rel.replace("\\", "/")
    if norm.startswith("docs/brainstorms/"):
        return True
    if norm.startswith("docs/decisions/") and not norm.endswith("INDEX.md") and not norm.endswith(
        "SUPERSEDED.log"
    ):
        return True
    return False


def redact_path(src_rel: str, private: bool) -> str:
    if not private:
        return src_rel
    parts = src_rel.split("/")
    if len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}/[redacted-private]"
    return "[redacted-private]"


def parse_gap_backlog(content: str) -> list[dict[str, str]]:
    gaps: list[dict[str, str]] = []
    for line in content.splitlines():
        m = re.match(r"^\|\s*(GAP-\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|", line)
        if m:
            gaps.append(
                {"gap_id": m.group(1).strip(), "status": m.group(2).strip(), "title": m.group(3).strip()}
            )
    return gaps


def gap_unit_id(gap_id: str, title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40] or "gap"
    num = gap_id.replace("GAP-", "")
    return f"gap-{num}-{slug}"


def prd_unit_id(prd_dir_name: str) -> str:
    m = re.match(r"^(\d+)-(.+)$", prd_dir_name)
    if not m:
        return f"prd-{slugify(prd_dir_name)}"
    return f"prd-{m.group(1)}-{m.group(2)}"


def slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def parse_frontmatter_fields(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def backfill_frontmatter(existing: str, fields: dict[str, str]) -> str:
    fm = parse_frontmatter_fields(existing)
    fm.update(fields)
    lines = ["---"]
    for key in (
        "id",
        "type",
        "status",
        "title",
        "visibility",
        "depends",
        "blocks",
        "supersedes",
        "extends",
        "absorbs",
        "priority",
        "tags",
    ):
        if key not in fm:
            continue
        val = fm[key]
        lines.append(f"{key}: {val}")
    lines.append("---")
    body = existing
    if existing.startswith("---"):
        end = existing.find("\n---", 3)
        if end != -1:
            body = existing[end + 4 :].lstrip("\n")
    return "\n".join(lines) + "\n\n" + body.lstrip("\n")


def discover_plan(root: Path) -> MigrationPlan:
    worktree = git_root(root)
    dirs = planning_paths.load_planning_dirs(root)
    prds_root = worktree / dirs.prds
    plan = MigrationPlan()
    plan.config_flip = {"planningDir": "docs/planning"}

    if prds_root.is_dir():
        for entry in sorted(prds_root.iterdir()):
            if not entry.is_dir():
                continue
            if not re.match(r"^\d+-", entry.name):
                continue
            unit_id = prd_unit_id(entry.name)
            dst_dir = f"docs/planning/prd/{unit_id}"
            for src_file in sorted(entry.rglob("*")):
                if not src_file.is_file():
                    continue
                src_rel = rel(root, src_file)
                rel_under = src_file.relative_to(entry)
                dst_rel = f"{dst_dir}/{rel_under}".replace("\\", "/")
                if rel_under.name.endswith(".md") and rel_under.parent == Path(".") and "-prd-" in rel_under.name:
                    slug = entry.name.split("-", 1)[1]
                    dst_rel = f"{dst_dir}/{unit_id}-prd-{slug}.md"
                plan.relocations.append(
                    Relocation(src=src_rel, dst=dst_rel, kind="prd-artifact")
                )

        gap_backlog = prds_root / "GAP-BACKLOG.md"
        if gap_backlog.is_file():
            content = gap_backlog.read_text(encoding="utf-8")
            for gap in parse_gap_backlog(content):
                uid = gap_unit_id(gap["gap_id"], gap["title"])
                plan.gap_id_map[gap["gap_id"]] = uid
                src_rel = f"docs/prds/gaps/{gap['gap_id']}.md"
                dst_rel = f"docs/planning/gap/{uid}/{uid}.md"
                body = f"# {gap['title']}\n\nMigrated from {gap['gap_id']}.\n"
                plan.relocations.append(
                    Relocation(
                        src=src_rel,
                        dst=dst_rel,
                        kind="gap-row",
                        gap_id=gap["gap_id"],
                        gap_status=gap["status"],
                        gap_title=gap["title"],
                        source_body=body,
                    )
                )

        feedback = prds_root / "FEEDBACK-CHECKLIST.md"
        if feedback.is_file():
            content = feedback.read_text(encoding="utf-8")
            for line in content.splitlines():
                line = line.strip()
                if line.startswith("- "):
                    plan.feedback_items.append(line[2:])
            uid = "gap-feedback-checklist"
            plan.relocations.append(
                Relocation(
                    src=rel(root, feedback),
                    dst=f"docs/planning/gap/{uid}/{uid}.md",
                    kind="feedback-checklist",
                )
            )

    brainstorms = worktree / "docs/brainstorms"
    if brainstorms.is_dir():
        for src_file in sorted(brainstorms.rglob("*.md")):
            if src_file.name.endswith(".md"):
                slug = slugify(src_file.stem)
                uid = f"brainstorm-{slug[:48]}"
                plan.relocations.append(
                    Relocation(
                        src=rel(root, src_file),
                        dst=f"docs/planning/brainstorm/{uid}/{uid}.md",
                        kind="brainstorm",
                    )
                )

    decisions = worktree / dirs.decisions
    if decisions.is_dir():
        for src_file in sorted(decisions.iterdir()):
            if src_file.is_file() and src_file.suffix == ".md" and src_file.name != "INDEX.md":
                slug = slugify(src_file.stem)
                uid = f"decision-{slug[:48]}"
                plan.relocations.append(
                    Relocation(
                        src=rel(root, src_file),
                        dst=f"docs/planning/decision/{uid}/{uid}.md",
                        kind="decision",
                    )
                )
        idx = decisions / "INDEX.md"
        if idx.is_file():
            plan.relocations.append(
                Relocation(
                    src=rel(root, idx),
                    dst="docs/planning/decision/INDEX.md",
                    kind="decision-index",
                )
            )

    return plan


def scan_runstate(root: Path) -> list[dict[str, Any]]:
    """Scan all linked git worktrees and .sw-worktrees for active deliver run-state."""
    worktree = git_root(root)
    hits: list[dict[str, Any]] = []
    search_roots: list[Path] = [worktree]

    proc = subprocess.run(
        ["git", "-C", str(worktree), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        current: dict[str, str] = {}
        for line in proc.stdout.splitlines():
            if line.startswith("worktree "):
                if current.get("path"):
                    search_roots.append(Path(current["path"]))
                current = {"path": line.split(" ", 1)[1].strip()}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1].strip()
        if current.get("path"):
            search_roots.append(Path(current["path"]))

    sw_root = worktree / ".sw-worktrees"
    if sw_root.is_dir():
        for wt in sw_root.iterdir():
            if wt.is_dir():
                search_roots.append(wt)

    seen: set[Path] = set()
    for base in search_roots:
        base = base.resolve()
        if base in seen:
            continue
        seen.add(base)
        cursor = base / ".cursor"
        if not cursor.is_dir():
            continue
        for state_file in cursor.glob("sw-deliver-state*.json"):
            try:
                data = json.loads(state_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            verdict = str(data.get("verdict", "")).lower()
            if verdict in ("running", "in-flight", "in-flight"):
                hits.append(
                    {
                        "path": str(state_file.relative_to(base)).replace("\\", "/"),
                        "worktree": str(base),
                        "verdict": data.get("verdict"),
                    }
                )
        runs = cursor / "sw-deliver-runs"
        if runs.is_dir():
            for run_dir in runs.iterdir():
                status = run_dir / "status.json"
                if status.is_file():
                    try:
                        data = json.loads(status.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if str(data.get("verdict", "")).lower() in ("running", "in-flight"):
                        hits.append(
                            {
                                "path": str(status.relative_to(base)).replace("\\", "/"),
                                "worktree": str(base),
                                "verdict": data.get("verdict"),
                            }
                        )

    return hits


def acquire_lock(root: Path) -> None:
    lp = lock_path(root)
    if lp.exists():
        fail("migration lock already held", exit_code=20, lock=LOCK_REL)
    runs = scan_runstate(root)
    if runs:
        fail("active deliver run-state detected", exit_code=20, runs=runs)
    payload = {"heldAt": time.time(), "pid": os.getpid(), "host": os.uname().nodename}
    write_json(lp, payload)


def release_lock(root: Path) -> None:
    lp = lock_path(root)
    if lp.is_file():
        lp.unlink()


def assert_lock_held(root: Path) -> None:
    if not lock_path(root).is_file():
        fail("migration lock not held", exit_code=20)


def scope_check(touched: list[str]) -> list[str]:
    violations: list[str] = []
    for path in touched:
        norm = path.replace("\\", "/")
        if any(norm == p or norm.startswith(p) for p in ALLOWED_TOUCH_PREFIXES):
            continue
        if norm.startswith(".cursor/planning-migration") or norm.startswith(".cursor/planning-path"):
            continue
        violations.append(norm)
    return violations


def stage_relocations(root: Path, plan: MigrationPlan) -> Path:
    worktree = git_root(root)
    staging = staging_path(root)
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    for item in plan.relocations:
        dst = staging / item.dst
        dst.parent.mkdir(parents=True, exist_ok=True)
        if item.kind == "gap-row" and item.source_body:
            uid = Path(item.dst).parent.name
            fields = {
                "id": uid,
                "type": "gap",
                "status": item.gap_status or "open",
                "title": item.gap_title or uid,
                "visibility": "public",
            }
            dst.write_bytes(backfill_frontmatter(item.source_body, fields).encode("utf-8"))
            continue
        src = worktree / item.src
        if not src.is_file():
            continue
        content = src.read_bytes()
        if item.dst.endswith(".md") and item.kind in ("prd-artifact", "brainstorm", "decision", "feedback-checklist"):
            body_text = content.decode("utf-8")
            fields: dict[str, str] = {}
            if item.kind == "feedback-checklist":
                fields = {"id": "gap-feedback-checklist", "type": "gap", "status": "open", "title": "Feedback checklist", "visibility": "public"}
            elif item.kind == "brainstorm":
                uid = Path(item.dst).parent.name
                fields = {"id": uid, "type": "brainstorm", "status": "proposed", "title": uid, "visibility": "private"}
            elif item.kind == "decision":
                uid = Path(item.dst).parent.name
                fields = {"id": uid, "type": "decision", "status": "proposed", "title": uid, "visibility": "private"}
            elif item.kind == "prd-artifact":
                uid = Path(item.dst).parent.name
                fields = {"id": uid, "type": "prd", "status": "complete", "title": uid, "visibility": "public"}
            if fields.get("id"):
                content = backfill_frontmatter(body_text, fields).encode("utf-8")
        dst.write_bytes(content)
    return staging


def apply_staging_to_worktree(root: Path, staging: Path) -> list[str]:
    worktree = git_root(root)
    touched: list[str] = []
    for src_file in staging.rglob("*"):
        if not src_file.is_file():
            continue
        rel_staged = src_file.relative_to(staging)
        dst = worktree / rel_staged
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_file, dst)
        touched.append(str(rel_staged).replace("\\", "/"))
    return touched


def build_reverse_map(plan: MigrationPlan) -> dict[str, str]:
    rev: dict[str, str] = {}
    for item in plan.relocations:
        rev[item.dst] = item.src
    return rev


def build_redirect_map(plan: MigrationPlan, root: Path) -> dict[str, str]:
    fwd: dict[str, str] = {}
    for item in plan.relocations:
        if is_private_source(root, item.src):
            continue
        fwd[item.src] = item.dst
    return fwd


def emit_operational_maps(root: Path, plan: MigrationPlan, *, after_commit: bool) -> None:
    if not after_commit:
        return
    worktree = git_root(root)
    reverse_raw = build_reverse_map(plan)
    reverse_redacted = {
        dst: redact_path(src, is_private_source(root, src)) for dst, src in reverse_raw.items()
    }
    write_json(
        reverse_map_path(root),
        {"version": 1, "reverse": reverse_redacted, "commit": _git_head(worktree)},
    )
    write_json(
        gap_map_path(root),
        {"version": 1, "map": plan.gap_id_map, "feedbackItems": plan.feedback_items},
    )
    write_json(
        worktree / REDIRECT_MAP_REL,
        {"version": 1, "map": build_redirect_map(plan, root)},
    )


def _git_head(worktree: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def flip_config(root: Path, planning_dir: str) -> None:
    worktree = git_root(root)
    rel_cfg = ".cursor/workflow.config.json"
    cfg_path = worktree / rel_cfg
    data = load_json(cfg_path) if cfg_path.is_file() else {}
    data["planningDir"] = planning_dir
    write_json(cfg_path, data)


def cmd_dry_run(root: Path) -> None:
    plan = discover_plan(root)
    emit(
        {
            "verdict": "pass",
            "mode": "dry-run",
            "relocationCount": len(plan.relocations),
            "gapIdMapSize": len(plan.gap_id_map),
            "feedbackItems": len(plan.feedback_items),
            "sample": [item.__dict__ for item in plan.relocations[:5]],
        }
    )


def cmd_write(root: Path, *, force: bool = False, skip_commit: bool = False) -> None:
    assert_lock_held(root)
    runs = scan_runstate(root)
    if runs and not force:
        fail("active deliver run-state — refuse write", runs=runs)
    plan = discover_plan(root)
    staging = stage_relocations(root, plan)
    touched = apply_staging_to_worktree(root, staging)
    violations = scope_check(touched)
    if violations:
        fail("migration scope violation", violations=violations)
    if not skip_commit:
        worktree = git_root(root)
        subprocess.run(["git", "-C", str(worktree), "add", "-A"], check=False)
        proc = subprocess.run(
            ["git", "-C", str(worktree), "commit", "-m", "feat(planning): migrate corpus to docs/planning (PRD 031)"],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 and "nothing to commit" not in (proc.stdout + proc.stderr):
            fail("git commit failed", stderr=proc.stderr)
    emit_operational_maps(root, plan, after_commit=True)
    flip_config(root, plan.config_flip.get("planningDir", "docs/planning"))
    shutil.rmtree(staging, ignore_errors=True)
    emit({"verdict": "pass", "mode": "write", "relocations": len(plan.relocations)})


def cmd_verify(root: Path) -> None:
    plan = discover_plan(root)
    worktree = git_root(root)
    errors: list[str] = []
    def body_after_fm(raw: bytes) -> bytes:
        text = raw.decode("utf-8")
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                return text[end + 4 :].lstrip("\n").encode("utf-8")
        return raw

    for item in plan.relocations:
        dst = worktree / item.dst
        if not dst.is_file():
            errors.append(f"missing destination: {item.dst}")
            continue
        if item.kind == "gap-row" and item.source_body:
            expected = item.source_body.encode("utf-8")
            actual = body_after_fm(dst.read_bytes())
            if expected.strip() != actual.strip():
                errors.append(f"gap body drift: {item.dst}")
            continue
        src = worktree / item.src
        if src.is_file():
            if body_after_fm(src.read_bytes()) != body_after_fm(dst.read_bytes()):
                errors.append(f"body drift: {item.dst}")
    rev = load_json(reverse_map_path(root)).get("reverse", {})
    if not rev:
        errors.append("reverse map missing")
    gap_data = load_json(gap_map_path(root))
    if plan.gap_id_map:
        stored = gap_data.get("map", {})
        for gid, uid in plan.gap_id_map.items():
            if stored.get(gid) != uid:
                errors.append(f"gap map mismatch: {gid}")
    feedback_stored = gap_data.get("feedbackItems", [])
    if plan.feedback_items and feedback_stored != plan.feedback_items:
        errors.append("feedback checklist drift")
    if errors:
        fail("verify failed", errors=errors, exit_code=20)
    emit({"verdict": "pass", "mode": "verify", "checked": len(plan.relocations)})


def cmd_rollback(root: Path, *, force: bool = False) -> None:
    worktree = git_root(root)
    rev_path = reverse_map_path(root)
    if not rev_path.is_file():
        fail("reverse map missing — cannot rollback")
    rev_data = load_json(rev_path)
    reverse: dict[str, str] = rev_data.get("reverse", {})
    planning_dir = worktree / "docs/planning"
    if planning_dir.is_dir() and not force:
        for path in planning_dir.rglob("*"):
            if path.is_file() and path.stat().st_mtime > rev_path.stat().st_mtime:
                fail("post-migration edits detected — use --force", path=str(path))
    flip_config(root, "docs/prds")
    for dst_rel, src_rel in reverse.items():
        dst = worktree / dst_rel
        src = worktree / src_rel
        if dst.is_file():
            dst.unlink()
        if src_rel.endswith(".md") and not src.parent.exists():
            src.parent.mkdir(parents=True, exist_ok=True)
    for map_path in (reverse_map_path(root), gap_map_path(root), worktree / REDIRECT_MAP_REL):
        if map_path.is_file():
            map_path.unlink()
    release_lock(root)
    emit({"verdict": "pass", "mode": "rollback", "restored": len(reverse)})


def cmd_lock_acquire(root: Path) -> None:
    acquire_lock(root)
    emit({"verdict": "pass", "mode": "lock-acquire"})


def cmd_lock_release(root: Path) -> None:
    release_lock(root)
    emit({"verdict": "pass", "mode": "lock-release"})


def cmd_scan_runstate(root: Path) -> None:
    runs = scan_runstate(root)
    emit({"verdict": "pass", "runs": runs, "count": len(runs)})


def main() -> None:
    parser = argparse.ArgumentParser(description="Planning corpus migration tool")
    parser.add_argument("repo_root")
    parser.add_argument(
        "command",
        choices=["dry-run", "write", "verify", "rollback", "lock-acquire", "lock-release", "scan-runstate"],
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-commit", action="store_true")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()

    handlers = {
        "dry-run": lambda: cmd_dry_run(root),
        "write": lambda: cmd_write(root, force=args.force, skip_commit=args.skip_commit),
        "verify": lambda: cmd_verify(root),
        "rollback": lambda: cmd_rollback(root, force=args.force),
        "lock-acquire": lambda: cmd_lock_acquire(root),
        "lock-release": lambda: cmd_lock_release(root),
        "scan-runstate": lambda: cmd_scan_runstate(root),
    }
    handlers[args.command]()


if __name__ == "__main__":
    main()
