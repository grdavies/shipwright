#!/usr/bin/env python3
"""Legacy→migrated path redirect map consumer (PRD 031 R21)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths  # noqa: E402

REDIRECT_MAP_REL = ".cursor/planning-path-redirect-map.json"
MATERIALIZED_PREFIX = ".cursor/planning-materialized"

REDIRECT_CONSUMERS: tuple[str, ...] = (
    "scripts/wave_deliver_loop.py",
    "scripts/wave_deliver.py",
    "scripts/wave_spec_seed.py",
    "scripts/check-frozen.py",
    "scripts/wave_living_docs.py",
    "scripts/planning_deliver_gate.py",
)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def redirect_map_path(root: Path) -> Path:
    return planning_paths.git_root(root) / REDIRECT_MAP_REL


def load_redirect_map(root: Path) -> dict[str, str]:
    path = redirect_map_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    mapping = data.get("map") if isinstance(data, dict) else data
    if not isinstance(mapping, dict):
        return {}
    return {str(k): str(v) for k, v in mapping.items()}


def resolve_path(root: Path, rel_path: str) -> str:
    """Resolve a repo-relative path through the redirect map when present."""
    norm = rel_path.replace("\\", "/")
    if norm.startswith("./"):
        norm = norm[2:]
    mapping = load_redirect_map(root)
    if norm in mapping:
        return mapping[norm]
    for legacy, migrated in mapping.items():
        legacy_base = legacy.rstrip("/")
        if norm == legacy_base or norm.startswith(legacy_base + "/"):
            suffix = norm[len(legacy_base) :].lstrip("/")
            base = migrated.rstrip("/")
            return f"{base}/{suffix}" if suffix else base
    return norm


def materialized_candidate(root: Path, rel_path: str) -> Path:
    """Return the materialized mirror path for a logical body-path (PRD 056 R18)."""
    norm = rel_path.replace("\\", "/").lstrip("./")
    if ".." in norm.split("/"):
        fail("body path contains ..", bodyPath=rel_path)
    return planning_paths.git_root(root) / MATERIALIZED_PREFIX / norm


def resolve_readable_path(root: Path, rel_path: str) -> tuple[str, Path] | tuple[None, None]:
    """Resolve a readable path: redirect map, logical file, then materialized fallback."""
    resolved_rel = resolve_path(root, rel_path)
    worktree = planning_paths.git_root(root)
    try:
        logical = planning_paths.resolve_contained(worktree, resolved_rel)
    except planning_paths.PathEscapeError:
        return None, None
    if logical.is_file():
        return resolved_rel, logical
    from host_lib import load_workflow_config
    from planning_store import resolve_effective_backend

    cfg = load_workflow_config(worktree)
    if resolve_effective_backend(worktree, cfg).get("effective") != "issue-store":
        return None, None
    materialized = materialized_candidate(worktree, resolved_rel)
    if materialized.is_file():
        mat_rel = f"{MATERIALIZED_PREFIX}/{resolved_rel}"
        return mat_rel, materialized
    return None, None


def cmd_resolve(root: Path, args: list[str]) -> None:
    rel = None
    i = 0
    while i < len(args):
        if args[i] == "--path" and i + 1 < len(args):
            rel = args[i + 1]
            i += 2
            continue
        i += 1
    if not rel:
        fail("--path required")
    resolved = resolve_path(root, rel)
    emit({"verdict": "pass", "input": rel, "resolved": resolved})


def cmd_consumers(_root: Path) -> None:
    emit({"verdict": "pass", "consumers": list(REDIRECT_CONSUMERS)})


def cmd_map(root: Path) -> None:
    mapping = load_redirect_map(root)
    emit({"verdict": "pass", "map": mapping, "path": REDIRECT_MAP_REL})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: planning_path_redirect.py <repo-root> <command> ...")
    root = Path(args[0]).resolve()
    cmd_args = args[2:] if len(args) > 2 else []
    command = args[1] if len(args) > 1 else ""

    commands = {
        "resolve": lambda: cmd_resolve(root, cmd_args),
        "consumers": lambda: cmd_consumers(root),
        "map": lambda: cmd_map(root),
    }
    handler = commands.get(command)
    if not handler:
        fail(f"unknown command: {command}")
    handler()


if __name__ == "__main__":
    main()
