#!/usr/bin/env python3
"""PRD 034 Phase 4 — provision-time materialization + commit-boundary barrier (R7, R8)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config
from planning_store import (
    content_hash,
    get_backend,
    planning_section,
    resolve_backend_id,
    store_section,
)
import planning_path_redirect
import planning_paths
import planning_visibility as planning_vis

SCRIPT_DIR = Path(__file__).resolve().parent

MATERIALIZED_PREFIX = ".cursor/planning-materialized"
PIN_STATE_KEY = "planningStorePin"
SPEC_TYPES = frozenset({"prd", "tasks", "amendment"})


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def git_root(start: Path | None = None) -> Path:
    cwd = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def is_ci_or_host() -> bool:
    if os.environ.get("SW_FORCE_MATERIALIZE") == "1":
        return False
    if os.environ.get("SW_SKIP_MATERIALIZE") == "1":
        return True
    if os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("GITHUB_ACTIONS", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return False


def store_revision(cfg: dict[str, Any]) -> str:
    store = store_section(cfg)
    payload = json.dumps(store, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def materialized_root(worktree: Path) -> Path:
    return worktree / MATERIALIZED_PREFIX


def materialized_rel(body_rel: str) -> str:
    safe = body_rel.replace("\\", "/").lstrip("/")
    if ".." in safe.split("/"):
        fail("body path contains ..", bodyPath=body_rel)
    return f"{MATERIALIZED_PREFIX}/{safe}"


def materialized_dest(worktree: Path, body_rel: str) -> Path:
    rel = materialized_rel(body_rel)
    parts = Path(rel)
    if ".." in parts.parts:
        fail("body path contains ..", bodyPath=body_rel)
    worktree_resolved = worktree.resolve()
    dest = (worktree_resolved / parts).resolve()
    try:
        dest.relative_to(worktree_resolved)
    except ValueError:
        fail("materialized path escapes worktree", bodyPath=body_rel)
    return dest


def parse_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    end = content.find("\n---", 3)
    if end == -1:
        return {}
    block = content[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            key, val = line.split(":", 1)
            out[key.strip()] = val.strip()
    return out


def unit_from_path(path: Path, root: Path) -> dict[str, Any]:
    rel = str(path.relative_to(root)).replace("\\", "/")
    fm = parse_frontmatter(path.read_text(encoding="utf-8"))
    unit: dict[str, Any] = {
        "id": fm.get("id") or path.stem,
        "type": fm.get("type") or "prd",
        "status": fm.get("status") or "proposed",
        "title": fm.get("title") or path.stem,
        "bodyPath": rel,
    }
    if fm.get("visibility"):
        unit["visibility"] = fm["visibility"]
    if fm.get("contentClass"):
        unit["contentClass"] = fm["contentClass"]
    if fm.get("storeRevision"):
        unit["storeRevision"] = fm["storeRevision"]
    return unit


def resolve_path_visibility(root: Path, path: Path) -> str:
    cfg = load_workflow_config(root)
    return planning_vis.resolve_unit_visibility(unit_from_path(path, root), cfg)["visibility"]


def is_private_spec(path: Path, root: Path) -> bool:
    unit = unit_from_path(path, root)
    unit_type = str(unit.get("type") or "prd").lower()
    if unit_type not in SPEC_TYPES and str(unit.get("contentClass") or "").lower() not in SPEC_TYPES:
        return False
    vis = resolve_path_visibility(root, path)
    return planning_vis.body_is_redacted(vis)


def discover_private_spec_units(root: Path, task_list_rel: str) -> list[dict[str, Any]]:
    task_list_rel = planning_path_redirect.resolve_path(root, task_list_rel)
    task_path = planning_paths.resolve_contained(root, task_list_rel)
    if not task_path.is_file():
        fail(f"task list not found: {task_list_rel}")
    docs_dir = task_path.parent
    units: list[dict[str, Any]] = []
    if not docs_dir.is_dir():
        return units
    for path in sorted(docs_dir.rglob("*.md")):
        if not path.is_file():
            continue
        if path.name.startswith("tasks-"):
            continue
        if is_private_spec(path, root):
            units.append(unit_from_path(path, root))
    return units


def secret_scan_file(path: Path) -> None:
    proc = subprocess.run(
        [str(SCRIPT_DIR / "secret-scan.py"), "file", str(path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(
            proc.stderr.strip() or "secret-scan failed after materialize",
            exit_code=20,
            halt="secret-scan",
            path=str(path),
        )


def load_deliver_state(root: Path, target: str | None = None) -> dict[str, Any]:
    from wave_state import load_deliver_state as _load

    return _load(root, target=target)


def save_deliver_state(root: Path, state: dict[str, Any], *, target: str | None = None) -> None:
    from wave_state import save_deliver_state as _save

    _save(root, state, target=target)


def read_pin(state: dict[str, Any]) -> dict[str, Any] | None:
    pin = state.get(PIN_STATE_KEY)
    return pin if isinstance(pin, dict) else None


def write_pin(
    state: dict[str, Any],
    *,
    backend: str,
    revision: str,
    paths: list[str],
) -> dict[str, Any]:
    existing = read_pin(state) or {}
    merged_paths = sorted(set(existing.get("materializedPaths") or []) | set(paths))
    state[PIN_STATE_KEY] = {
        "backend": backend,
        "revision": revision,
        "materializedPaths": merged_paths,
    }
    return state


def validate_store_pin(root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = state if state is not None else load_deliver_state(root)
    pin = read_pin(state)
    if not pin:
        return {"verdict": "ok", "reason": "no-pin"}
    cfg = load_workflow_config(root)
    current_backend = resolve_backend_id(cfg)
    current_revision = store_revision(cfg)
    pinned_backend = str(pin.get("backend") or "")
    pinned_revision = str(pin.get("revision") or "")
    if current_backend != pinned_backend or current_revision != pinned_revision:
        return {
            "verdict": "fail",
            "error": "planning.store backend or revision changed mid-run",
            "halt": "backend-swap",
            "remediation": "finish or abort the deliver run before changing planning.store; re-provision phases",
            "pinned": {"backend": pinned_backend, "revision": pinned_revision},
            "current": {"backend": current_backend, "revision": current_revision},
        }
    return {
        "verdict": "ok",
        "backend": current_backend,
        "revision": current_revision,
    }


def collect_staged_paths(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMRTUXB"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "git diff --cached failed")
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def collect_push_paths(root: Path) -> list[str]:
    branch = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    upstream = ""
    if branch:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "for-each-ref",
                "--format=%(upstream:short)",
                f"refs/heads/{branch}",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            upstream = proc.stdout.strip()
    if not upstream:
        return collect_staged_paths(root)
    range_ref = f"{upstream}..HEAD"
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", range_ref],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def paths_under_prefix(paths: list[str]) -> list[str]:
    prefix = f"{MATERIALIZED_PREFIX}/"
    return [p for p in paths if p == MATERIALIZED_PREFIX or p.startswith(prefix)]


def contains_private_body_marker(text: str) -> bool:
    return planning_vis.REDACTED_BODY_MARKER in text


def collect_diff_paths(root: Path, base_ref: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", base_ref, "HEAD"],
            capture_output=True,
            text=True,
        )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or f"git diff failed for base {base_ref!r}")
    return [line.strip().replace("\\", "/") for line in proc.stdout.splitlines() if line.strip()]


def scan_diff_for_violations(root: Path, base_ref: str) -> dict[str, Any]:
    paths = collect_diff_paths(root, base_ref)
    prefix_hits = paths_under_prefix(paths)
    marker_hits: list[str] = []
    for rel in paths:
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", f"{base_ref}...HEAD", "--", rel],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            proc = subprocess.run(
                ["git", "-C", str(root), "diff", base_ref, "HEAD", "--", rel],
                capture_output=True,
                text=True,
            )
        diff_text = proc.stdout
        path = root / rel
        texts = [diff_text]
        if path.is_file():
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        if any(contains_private_body_marker(text) for text in texts if text):
            marker_hits.append(rel)
    if prefix_hits or marker_hits:
        return {
            "verdict": "fail",
            "error": "materialized prefix or private-body marker in PR diff",
            "prefixPaths": prefix_hits,
            "markerPaths": marker_hits,
        }
    return {"verdict": "ok", "scanned": len(paths)}


def cmd_provision(root: Path, args: argparse.Namespace) -> int:
    if is_ci_or_host():
        emit({"verdict": "skipped", "reason": "ci-or-host-never-materializes"})
        return 0
    worktree = Path(args.worktree).resolve()
    if not worktree.is_dir():
        fail(f"worktree not found: {worktree}")
    task_list = args.task_list
    if not task_list:
        fail("--task-list required")
    pin_check = validate_store_pin(root)
    if pin_check.get("verdict") == "fail":
        emit(pin_check, 20)
    state = load_deliver_state(root, target=args.target)
    units = discover_private_spec_units(root, task_list)
    cfg = load_workflow_config(root)
    backend_id = resolve_backend_id(cfg)
    revision = store_revision(cfg)
    backend = get_backend(root, cfg)
    materialized_paths: list[str] = []
    copied: list[dict[str, str]] = []
    for unit in units:
        body_rel = str(unit["bodyPath"])
        dest = materialized_dest(worktree, body_rel)
        result = backend.materialize(str(unit["id"]), body_rel, dest)
        if result.verdict != "ok":
            fail(
                f"materialize failed for {unit['id']}",
                unitId=unit["id"],
                bodyPath=body_rel,
                backend=backend_id,
                reason=result.reason,
            )
        secret_scan_file(dest)
        rel_dest = str(dest.relative_to(worktree)).replace("\\", "/")
        materialized_paths.append(rel_dest)
        copied.append({"unitId": str(unit["id"]), "dest": rel_dest, "hash": result.hash or ""})
    write_pin(
        state,
        backend=backend_id,
        revision=revision,
        paths=materialized_paths,
    )
    save_deliver_state(root, state, target=args.target)
    emit(
        {
            "verdict": "ok",
            "action": "materialize-provision",
            "worktree": str(worktree),
            "backend": backend_id,
            "revision": revision,
            "units": copied,
            "prefix": MATERIALIZED_PREFIX,
        }
    )
    return 0


def cmd_validate_pin(root: Path, _args: argparse.Namespace) -> int:
    result = validate_store_pin(root)
    emit(result, 0 if result.get("verdict") == "ok" else 20)
    return 0


def cmd_teardown(_root: Path, args: argparse.Namespace) -> int:
    worktree = Path(args.worktree).resolve()
    mat = materialized_root(worktree)
    removed = False
    if mat.exists():
        shutil.rmtree(mat)
        removed = True
    emit({"verdict": "ok", "action": "materialize-teardown", "removed": removed, "path": str(mat)})
    return 0


def cmd_sweep_orphans(_root: Path, args: argparse.Namespace) -> int:
    raw = args.paths_json or "[]"
    try:
        paths = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"invalid paths JSON: {exc}")
    if not isinstance(paths, list):
        fail("paths must be a JSON array")
    swept: list[str] = []
    for entry in paths:
        path = Path(str(entry)).expanduser().resolve()
        if not path.is_dir():
            continue
        if path.name == "planning-materialized" and path.parent.name == ".cursor":
            shutil.rmtree(path)
            swept.append(str(path))
    emit({"verdict": "ok", "action": "materialize-sweep", "swept": swept})
    return 0


def cmd_guard_staged(root: Path, args: argparse.Namespace) -> int:
    paths = collect_push_paths(root) if args.push else collect_staged_paths(root)
    hits = paths_under_prefix(paths)
    if hits:
        emit(
            {
                "verdict": "fail",
                "error": "materialized prefix path staged for commit/push",
                "paths": hits,
                "prefix": MATERIALIZED_PREFIX,
            },
            20,
        )
        return 20
    emit({"verdict": "ok", "action": "materialized-prefix-guard", "checked": len(paths)})
    return 0


def cmd_scan_diff(root: Path, args: argparse.Namespace) -> int:
    base = args.base or "origin/main"
    result = scan_diff_for_violations(root, base)
    emit(result, 0 if result.get("verdict") == "ok" else 20)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Planning materialization (PRD 034)")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    p_provision = sub.add_parser("provision")
    p_provision.add_argument("--worktree", required=True)
    p_provision.add_argument("--task-list", required=True)
    p_provision.add_argument("--target")

    sub.add_parser("validate-pin")

    p_teardown = sub.add_parser("teardown")
    p_teardown.add_argument("--worktree", required=True)

    p_sweep = sub.add_parser("sweep-orphans")
    p_sweep.add_argument("--paths-json", default="[]")

    p_guard = sub.add_parser("guard-staged")
    p_guard.add_argument("--push", action="store_true")

    p_scan = sub.add_parser("scan-diff")
    p_scan.add_argument("--base", default="origin/main")

    args = parser.parse_args()
    root = git_root(Path(args.root).resolve())

    if args.command == "provision":
        cmd_provision(root, args)
    elif args.command == "validate-pin":
        cmd_validate_pin(root, args)
    elif args.command == "teardown":
        cmd_teardown(root, args)
    elif args.command == "sweep-orphans":
        cmd_sweep_orphans(root, args)
    elif args.command == "guard-staged":
        cmd_guard_staged(root, args)
    elif args.command == "scan-diff":
        cmd_scan_diff(root, args)
    else:
        fail(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
