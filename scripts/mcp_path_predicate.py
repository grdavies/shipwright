#!/usr/bin/env python3
"""MCP embedded-path predicate for restore-plan emit and terminal prepare (PRD 362 R1/R4)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

SW_WORKTREES_SEGMENT = "/.sw-worktrees/"
TRACKED_DIST_MCP_REL = (
    "dist/codex/mcp/shipwright.json",
    "dist/opencode/mcp/shipwright.json",
)


def _canonical_repo_root(start: Path) -> Path:
    from primary_checkout_guard import canonical_repo_root

    return canonical_repo_root(start)


def primary_checkout_root(start: Path | None = None) -> Path:
    from primary_checkout_guard import primary_worktree_path

    root = _canonical_repo_root(start or Path.cwd())
    return primary_worktree_path(root).resolve()


def mcp_emit_repo_root(repo_root: Path) -> Path:
    """Resolve repo root for MCP path embedding — always the primary checkout when cwd is a worktree."""
    repo = repo_root.resolve()
    primary = primary_checkout_root(repo)
    if repo == primary:
        return repo
    return primary


def _normalize_path_text(value: str) -> str:
    return value.replace("\\", "/")


def embedded_path_forbidden(value: str, *, primary: Path | None = None) -> bool:
    """True when an embedded MCP path must not appear in tracked JSON (orch / worktree / non-primary)."""
    if not value or not isinstance(value, str):
        return False
    text = _normalize_path_text(value.strip())
    if SW_WORKTREES_SEGMENT in text:
        return True
    if "-orchestrator" in text and ".sw-worktrees" in text:
        return True
    primary = primary or primary_checkout_root()
    try:
        resolved = Path(value).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    primary_res = primary.resolve()
    if resolved == primary_res:
        return False
    sw_root = primary_res / ".sw-worktrees"
    try:
        resolved.relative_to(sw_root.resolve())
        return True
    except ValueError:
        pass
    if resolved != primary_res:
        proc_root = primary_res
        for wt in _listed_worktrees(proc_root):
            if resolved == wt.resolve() and wt.resolve() != primary_res:
                return True
    return False


def _listed_worktrees(repo_root: Path) -> list[Path]:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "list", "--porcelain"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return []
    paths: list[Path] = []
    for line in proc.stdout.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line.split(" ", 1)[1].strip()))
    return paths


def iter_mcp_embedded_strings(doc: dict[str, Any]) -> Iterable[str]:
    config_path = doc.get("config_path")
    if isinstance(config_path, str):
        yield config_path
    servers = doc.get("mcpServers")
    if not isinstance(servers, dict):
        return
    for entry in servers.values():
        if not isinstance(entry, dict):
            continue
        args = entry.get("args")
        if isinstance(args, list):
            for arg in args:
                if isinstance(arg, str):
                    yield arg
        elif isinstance(args, str):
            yield args


def mcp_document_violations(doc: dict[str, Any], *, primary: Path | None = None) -> list[str]:
    primary = primary or primary_checkout_root()
    out: list[str] = []
    for raw in iter_mcp_embedded_strings(doc):
        if embedded_path_forbidden(raw, primary=primary):
            out.append(raw)
    return out


def load_mcp_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"MCP JSON must be an object: {path}")
    return data


def tracked_dist_mcp_paths(root: Path) -> list[Path]:
    return [root / rel for rel in TRACKED_DIST_MCP_REL]


def check_tracked_dist_mcp_json(root: Path) -> list[dict[str, Any]]:
    """Return violation records for on-disk tracked dist MCP configs."""
    primary = primary_checkout_root(root)
    violations: list[dict[str, Any]] = []
    for path in tracked_dist_mcp_paths(root):
        if not path.is_file():
            continue
        doc = load_mcp_json(path)
        bad = mcp_document_violations(doc, primary=primary)
        if bad:
            violations.append({"path": str(path.relative_to(root)), "embedded": bad})
    return violations


def check_staged_dist_mcp_json(root: Path) -> list[dict[str, Any]]:
    """Apply the same predicate to staged dist MCP JSON when present."""
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return []
    rels = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    primary = primary_checkout_root(root)
    violations: list[dict[str, Any]] = []
    for rel in TRACKED_DIST_MCP_REL:
        if rel not in rels:
            continue
        path = root / rel
        if not path.is_file():
            continue
        doc = load_mcp_json(path)
        bad = mcp_document_violations(doc, primary=primary)
        if bad:
            violations.append({"path": rel, "embedded": bad, "staged": True})
    return violations


def assert_terminal_prepare_mcp_paths(root: Path) -> None:
    """Fail-closed gate for deliver terminal prepare (R4)."""
    hits = check_tracked_dist_mcp_json(root) + check_staged_dist_mcp_json(root)
    if hits:
        raise RuntimeError(
            "terminal-prepare: tracked MCP JSON embeds forbidden worktree/orchestrator paths: "
            + json.dumps(hits, ensure_ascii=False)
        )


def validate_build_mcp_config(doc: dict[str, Any] | None, *, primary: Path | None = None) -> None:
    if not doc:
        return
    bad = mcp_document_violations(doc, primary=primary or primary_checkout_root())
    if bad:
        raise ValueError(
            "MCP config embeds forbidden worktree/orchestrator paths: " + ", ".join(bad)
        )
