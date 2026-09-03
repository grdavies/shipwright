#!/usr/bin/env python3
"""Optional project-intelligence integrations for exploration (PRD 331 R16, R21, R42)."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

import architecture_radar
import exploration_security
from memory_preflight import PreflightError, exploration_query
from repository_context import RepositoryContextError, from_root

INTELLIGENCE_SOURCES = ("repository", "radar", "vocabulary", "memory")

RepositoryDiscoverFn = Callable[[Path], dict[str, Any]]
RadarAdapterFn = Callable[[Path], dict[str, Any]]
VocabularyAdapterFn = Callable[[Path], dict[str, Any]]
MemoryQueryFn = Callable[[Path, str], dict[str, Any]]


def _git_toplevel(root: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


def _repository_layout_signals(root: Path) -> dict[str, Any]:
    signals: dict[str, Any] = {
        "hasGit": False,
        "topLevelDirs": [],
        "manifestFiles": [],
        "architectureArtifacts": [],
    }
    git_root = _git_toplevel(root)
    if git_root is None:
        return signals
    signals["hasGit"] = True
    try:
        children = sorted(
            item.name
            for item in git_root.iterdir()
            if item.is_dir() and not item.name.startswith(".")
        )
        signals["topLevelDirs"] = children[:20]
    except OSError:
        pass
    for rel in (
        "README.md",
        "pyproject.toml",
        "package.json",
        "go.mod",
        "Cargo.toml",
        ".shipwright/workflow.config.json",
        # shipwright-paths-exclusion: legacy manifest probe retained for brownfield detection
        ".cursor/workflow.config.json",
    ):
        if (git_root / rel).is_file():
            signals["manifestFiles"].append(rel)
    for rel in (
        "docs/architecture",
        "architecture",
        "core/sw-reference",
        ".cursor/sw-architecture-radar",
    ):
        if (git_root / rel).exists():
            signals["architectureArtifacts"].append(rel)
    return signals


def discover_repository_signals(
    root: Path,
    *,
    context_loader: Callable[[Path], Any] | None = None,
) -> dict[str, Any]:
    """Repository discovery with greenfield fallback (R16, R21)."""
    loader = context_loader or from_root
    layout = _repository_layout_signals(root)
    try:
        context = loader(root)
        envelope = {
            "projectId": context.project_id,
            "repoSlug": context.repo_slug,
            "remote": context.remote,
            "planningAuthority": context.planning_authority,
            "memoryNamespace": context.memory_namespace,
        }
        mode = "enriched" if layout["hasGit"] else "greenfield"
        return {
            "verdict": "ok",
            "source": "repository",
            "mode": mode,
            "blocking": False,
            "status": "available",
            "repository": envelope,
            "layout": layout,
        }
    except (RepositoryContextError, OSError, ValueError) as exc:
        return {
            "verdict": "degraded",
            "source": "repository",
            "mode": "greenfield",
            "blocking": False,
            "status": "degraded",
            "cause": str(exc),
            "repository": {},
            "layout": layout,
        }


def _radar_adapter(root: Path) -> dict[str, Any]:
    return architecture_radar.explore_radar_adapter(root)


def _vocabulary_adapter(root: Path) -> dict[str, Any]:
    return architecture_radar.explore_vocabulary_adapter(root)


def _memory_adapter(root: Path, query: str) -> dict[str, Any]:
    return exploration_query(root, query)


def collect_exploration_intelligence(
    root: Path,
    *,
    query: str = "",
    repository_fn: RepositoryDiscoverFn | None = None,
    radar_fn: RadarAdapterFn | None = None,
    vocabulary_fn: VocabularyAdapterFn | None = None,
    memory_fn: MemoryQueryFn | None = None,
) -> dict[str, Any]:
    """Aggregate optional intelligence inputs — all failures are non-blocking (R42)."""
    repo_loader = repository_fn or discover_repository_signals
    radar_loader = radar_fn or _radar_adapter
    vocabulary_loader = vocabulary_fn or _vocabulary_adapter
    memory_loader = memory_fn or _memory_adapter

    repository = repo_loader(root) if callable(repo_loader) else repo_loader(root)
    radar = radar_loader(root)
    vocabulary = vocabulary_loader(root)
    memory = memory_loader(root, query) if query else {
        "verdict": "degraded",
        "source": "memory",
        "status": "absent",
        "blocking": False,
        "cause": "query-not-provided",
        "results": [],
        "redacted": True,
    }

    sources = {
        "repository": repository,
        "radar": radar,
        "vocabulary": vocabulary,
        "memory": memory,
    }
    degraded = [
        name
        for name, payload in sources.items()
        if str(payload.get("status") or payload.get("verdict")) in {"degraded", "absent", "fail"}
        or payload.get("verdict") == "degraded"
    ]
    available = [name for name in INTELLIGENCE_SOURCES if name not in degraded]
    return {
        "verdict": "ok",
        "blocking": False,
        "degradedSources": degraded,
        "availableSources": available,
        "greenfield": repository.get("mode") == "greenfield",
        "sources": sources,
    }


def enrich_exploration_context(
    root: Path,
    map_document: Mapping[str, Any],
    *,
    query: str = "",
    collector: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Attach intelligence context without mutating destination progress invariants."""
    snapshot = (collector or collect_exploration_intelligence)(root, query=query)
    destination = map_document.get("destination") if isinstance(map_document.get("destination"), dict) else {}
    destination_ready = bool(str(destination.get("statement") or "").strip())
    return {
        "verdict": "ok",
        "blocking": False,
        "destinationReady": destination_ready,
        "destinationProgressInvariant": True,
        "intelligence": snapshot,
    }


def intelligence_blocks_destination(_snapshot: Mapping[str, Any]) -> bool:
    """Intelligence integrations must never block destination/model progress (R42)."""
    return False


# Traceability aliases for tests and callers
discover_repository = discover_repository_signals
collect_intelligence_context = collect_exploration_intelligence
blocks_destination_progress = intelligence_blocks_destination


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys

    from _sw.cli import run_module_main

    parser = argparse.ArgumentParser(description="Exploration intelligence integrations (PRD 331)")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover", help="Repository discovery with greenfield fallback")
    collect = sub.add_parser("collect", help="Collect degradable intelligence inputs")
    collect.add_argument("--query", default="")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.command == "discover":
        payload = discover_repository_signals(root)
    else:
        payload = collect_exploration_intelligence(root, query=args.query)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
