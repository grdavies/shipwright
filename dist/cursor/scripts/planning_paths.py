#!/usr/bin/env python3
"""Config-driven planning path resolution with realpath containment (PRD 031 R23/R7)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

DIR_DEFAULTS: dict[str, str] = {
    "planningDir": "docs/planning",
    "prdsDir": "docs/prds",
    "tasksDir": "docs/prds",
    "decisionsDir": "docs/decisions",
}

PATH_DEPENDENT_CONSUMERS: tuple[str, ...] = (
    "scripts/wave_spec_seed.py",
    "scripts/wave_deliver.py",
    "scripts/wave_living_docs.py",
)

LIVING_DOC_NAMES: tuple[str, ...] = (
    "INDEX.md",
    "COMPLETION-LOG.md",
    "GAP-BACKLOG.md",
)


class PathEscapeError(ValueError):
    """Resolved path escapes the worktree root."""


@dataclass(frozen=True)
class PlanningDirs:
    planning: str
    prds: str
    tasks: str
    decisions: str

    def as_dict(self) -> dict[str, str]:
        return {
            "planningDir": self.planning,
            "prdsDir": self.prds,
            "tasksDir": self.tasks,
            "decisionsDir": self.decisions,
        }


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
        raise PathEscapeError("not a git repository")
    return Path(proc.stdout.strip())


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}


def schema_dir_default(root: Path, key: str) -> str:
    for candidate in (
        root / ".sw/config.schema.json",
        root / "core/sw-reference/config.schema.json",
        Path(os.environ.get("CURSOR_PLUGIN_ROOT", "")) / ".sw/config.schema.json",
    ):
        if not candidate.is_file():
            continue
        try:
            schema = json.loads(candidate.read_text(encoding="utf-8"))
            props = schema.get("properties") or {}
            entry = props.get(key) or {}
            default = entry.get("default")
            if isinstance(default, str) and default:
                return default
        except json.JSONDecodeError:
            continue
    return DIR_DEFAULTS[key]


def load_planning_dirs(root: Path) -> PlanningDirs:
    cfg = load_workflow_config(root)

    def _dir(key: str) -> str:
        raw = cfg.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip().replace("\\", "/").rstrip("/")
        return schema_dir_default(root, key)

    return PlanningDirs(
        planning=_dir("planningDir"),
        prds=_dir("prdsDir"),
        tasks=_dir("tasksDir"),
        decisions=_dir("decisionsDir"),
    )


def join_rel(*parts: str) -> str:
    return str(Path(*parts)).replace("\\", "/")


def resolve_contained(root: Path, rel_or_abs: str | Path) -> Path:
    """Canonical realpath under worktree root; rejects .. and escape symlinks."""
    worktree = git_root(root)
    raw = Path(rel_or_abs)
    if ".." in raw.parts:
        raise PathEscapeError(f"path traversal rejected: {rel_or_abs}")
    candidate = raw if raw.is_absolute() else worktree / raw
    resolved = candidate.resolve()
    try:
        resolved.relative_to(worktree.resolve())
    except ValueError as exc:
        raise PathEscapeError(
            f"resolved path escapes worktree: {rel_or_abs} -> {resolved}"
        ) from exc
    return resolved


def rel_contained(root: Path, rel_or_abs: str | Path) -> str:
    worktree = git_root(root)
    return str(resolve_contained(root, rel_or_abs).relative_to(worktree.resolve()))


def prds_rel(dirs: PlanningDirs, name: str) -> str:
    return join_rel(dirs.prds, name)


def living_paths_rel(dirs: PlanningDirs) -> tuple[str, ...]:
    return tuple(prds_rel(dirs, name) for name in LIVING_DOC_NAMES)


def index_paths_rel(dirs: PlanningDirs) -> tuple[str, ...]:
    return (
        prds_rel(dirs, "INDEX.md"),
        join_rel(dirs.decisions, "INDEX.md"),
    )


def contention_serialized_defaults(dirs: PlanningDirs) -> list[str]:
    return [
        prds_rel(dirs, "INDEX.md"),
        join_rel(dirs.decisions, "INDEX.md"),
        "CHANGELOG.md",
        "version.txt",
        "doc-numbering",
    ]


def contention_default(root: Path) -> dict[str, list[str]]:
    dirs = load_planning_dirs(root)
    return {"serialized": contention_serialized_defaults(dirs)}


def path_under_prds(dirs: PlanningDirs, path: str) -> bool:
    norm = path.replace("\\", "/")
    prefix = dirs.prds.rstrip("/") + "/"
    return norm == dirs.prds or norm.startswith(prefix)


def path_under_decisions(dirs: PlanningDirs, path: str) -> bool:
    norm = path.replace("\\", "/")
    prefix = dirs.decisions.rstrip("/") + "/"
    return norm == dirs.decisions or norm.startswith(prefix)


def phase_touches_doc_numbering(paths: list[str], root: Path) -> bool:
    dirs = load_planning_dirs(root)
    for path in paths:
        if path_under_prds(dirs, path) or path_under_decisions(dirs, path):
            if not path.endswith("INDEX.md"):
                return True
    return False


def brainstorms_rel() -> str:
    return "docs/brainstorms"


def prd_unit_dir_for_artifact(root: Path, artifact: Path) -> Path:
    """Resolve PRD unit directory from an artifact path under prdsDir."""
    dirs = load_planning_dirs(root)
    worktree = git_root(root)
    resolved = resolve_contained(root, artifact)
    rel_parts = resolved.relative_to(worktree).parts
    prds_parts = Path(dirs.prds).parts
    if len(rel_parts) < len(prds_parts) + 1:
        raise PathEscapeError(f"artifact not under {dirs.prds}: {artifact}")
    if rel_parts[: len(prds_parts)] != prds_parts:
        raise PathEscapeError(f"artifact not under {dirs.prds}: {artifact}")
    return worktree.joinpath(*rel_parts[: len(prds_parts) + 1])


def scan_hardcoded_prds_literals(repo_root: Path) -> list[str]:
    """Return consumer paths that still contain a docs/prds literal."""
    hits: list[str] = []
    for rel in PATH_DEPENDENT_CONSUMERS:
        path = repo_root / rel
        if not path.is_file():
            hits.append(f"{rel} (missing)")
            continue
        text = path.read_text(encoding="utf-8")
        if "docs/prds" in text:
            hits.append(rel)
    return hits


def cmd_dirs(root: Path) -> None:
    dirs = load_planning_dirs(root)
    emit({"verdict": "pass", "dirs": dirs.as_dict()})


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
    try:
        resolved = resolve_contained(root, rel)
        emit(
            {
                "verdict": "pass",
                "relative": rel_contained(root, rel),
                "absolute": str(resolved),
            }
        )
    except PathEscapeError as exc:
        fail(str(exc), exit_code=20)


def cmd_living_paths(root: Path) -> None:
    dirs = load_planning_dirs(root)
    emit({"verdict": "pass", "paths": list(living_paths_rel(dirs))})


def cmd_index_paths(root: Path) -> None:
    dirs = load_planning_dirs(root)
    emit({"verdict": "pass", "paths": list(index_paths_rel(dirs))})


def cmd_contention_default(root: Path) -> None:
    emit({"verdict": "pass", **contention_default(root)})


def cmd_scan_literals(root: Path) -> None:
    hits = scan_hardcoded_prds_literals(root)
    if hits:
        fail("hardcoded docs/prds literals remain", consumers=hits, exit_code=20)
    emit({"verdict": "pass", "consumers": list(PATH_DEPENDENT_CONSUMERS)})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: planning_paths.py <repo-root> <command> ...")
    root = Path(args[0]).resolve()
    cmd_args = args[2:] if len(args) > 2 else []
    command = args[1] if len(args) > 1 else ""

    commands = {
        "dirs": lambda: cmd_dirs(root),
        "resolve": lambda: cmd_resolve(root, cmd_args),
        "living-paths": lambda: cmd_living_paths(root),
        "index-paths": lambda: cmd_index_paths(root),
        "contention-default": lambda: cmd_contention_default(root),
        "scan-literals": lambda: cmd_scan_literals(root),
    }
    handler = commands.get(command)
    if not handler:
        fail(f"unknown command: {command}")
    handler()


if __name__ == "__main__":
    main()
