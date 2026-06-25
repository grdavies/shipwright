#!/usr/bin/env python3
"""Idempotent spec-seed onto <type>/<slug> — single owner for /sw-doc and deliver-loop (R6/R57)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
SHIPWRIGHT_ROOT = SCRIPT_DIR.parent


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def git_toplevel(start: Path) -> Path:
    out = subprocess.check_output(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    return Path(out)


def git_run(args: list[str], cwd: Path, *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=check)


def load_default_branch(root: Path) -> str:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                cfg = json.loads(path.read_text(encoding="utf-8"))
                base = cfg.get("defaultBaseBranch")
                if isinstance(base, str) and base:
                    return base
            except json.JSONDecodeError:
                pass
    return "main"


def resolve_target_branch(root: Path, task_list_rel: str) -> tuple[str, str, Path]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SHIPWRIGHT_ROOT / "scripts/wave_deliver.py"),
            str(root),
            "preflight",
            "--task-list",
            task_list_rel,
            "--skip-base-check",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "preflight failed")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        fail(f"preflight returned invalid JSON: {exc}")
    branch = (data.get("target") or {}).get("branch")
    if not branch:
        fail("preflight missing target.branch")
    task_path = (root / task_list_rel).resolve()
    if not task_path.is_file():
        fail(f"task list not found: {task_list_rel}")
    docs_dir = task_path.parent
    slug = branch.split("/", 1)[1] if "/" in branch else branch
    return branch, slug, docs_dir


def docs_paths(docs_dir: Path, root: Path) -> list[Path]:
    rel = docs_dir.relative_to(root)
    paths: list[Path] = []
    if docs_dir.is_dir():
        for p in sorted(docs_dir.rglob("*")):
            if p.is_file() and "brainstorms" not in p.parts:
                paths.append(p)
    return paths


def rel_paths(root: Path, paths: list[Path]) -> list[str]:
    return [str(p.relative_to(root)) for p in paths]


def branch_has_docs_commit(top: Path, branch: str, doc_rels: list[str]) -> bool:
    if not doc_rels:
        return False
    show = git_run(["show-ref", "--verify", f"refs/heads/{branch}"], top, check=False)
    if show.returncode != 0:
        return False
    for rel in doc_rels:
        log = git_run(["log", "-1", "--format=%H", branch, "--", rel], top, check=False)
        if log.returncode != 0 or not log.stdout.strip():
            return False
    diff = git_run(["diff", "--quiet", branch, "--", *doc_rels], top, check=False)
    if diff.returncode == 1:
        return False
    return True


def cmd_spec_seed(root: Path, args: list[str]) -> None:
    task_list = parse_kv(args, "--task-list")
    if not task_list:
        fail("--task-list required")
    dry_run = has_flag(args, "--dry-run")
    top = git_toplevel(root)
    default = load_default_branch(top)
    branch, slug, docs_dir = resolve_target_branch(top, task_list)

    if branch == default:
        fail(f"refused: spec-seed never targets default branch {default!r}")

    doc_files = docs_paths(docs_dir, top)
    doc_rels = rel_paths(top, doc_files)
    if not doc_rels:
        fail(f"no files under {docs_dir.relative_to(top)}")

    current = git_run(["branch", "--show-current"], top, check=False).stdout.strip()
    status = git_run(["status", "--porcelain"], top, check=False).stdout

    if current == branch and status.strip():
        fail(
            f"primary checkout is dirty on {branch} — commit or stash before spec-seed",
            exit_code=20,
            halt="dirty-primary",
            remediation=f"git stash push -m 'pre-spec-seed' && git checkout {default}",
        )

    if branch_has_docs_commit(top, branch, doc_rels):
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "branch": branch,
                "docsDir": str(docs_dir.relative_to(top)),
                "note": "already seeded (idempotent no-op)",
                "skipped": True,
            }
        )

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "dry_run": True,
                "branch": branch,
                "docsDir": str(docs_dir.relative_to(top)),
                "files": doc_rels,
            }
        )

    prev = current or default
    base_ref = default
    if git_run(["show-ref", "--verify", f"refs/heads/{branch}"], top, check=False).returncode == 0:
        base_ref = branch

    git_run(["checkout", "-B", branch, base_ref], top)
    git_run(["add", "--"] + doc_rels, top)
    diff_cached = git_run(["diff", "--cached", "--quiet"], top, check=False)
    if diff_cached.returncode == 0:
        if prev and prev != branch:
            git_run(["checkout", prev], top, check=False)
        emit(
            {
                "verdict": "pass",
                "action": "spec-seed",
                "branch": branch,
                "note": "docs already match branch HEAD (idempotent)",
                "skipped": True,
            }
        )

    msg = f"docs: freeze PRD and tasks for {slug}"
    git_run(["commit", "-m", msg], top)
    head = git_run(["rev-parse", "HEAD"], top).stdout.strip()
    if prev and prev != branch:
        git_run(["checkout", prev], top, check=False)

    emit(
        {
            "verdict": "pass",
            "action": "spec-seed",
            "branch": branch,
            "commit": head,
            "docsDir": str(docs_dir.relative_to(top)),
            "files": doc_rels,
        }
    )


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: wave_spec_seed.py <root> spec-seed --task-list PATH [--dry-run]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else "spec-seed"
    args = sys.argv[3:]
    if cmd != "spec-seed":
        fail(f"unknown command: {cmd}")
    cmd_spec_seed(root, args)


if __name__ == "__main__":
    main()
