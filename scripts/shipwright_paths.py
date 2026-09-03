#!/usr/bin/env python3
"""Central path-resolution authority for Shipwright-owned state (PRD 342 R8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

STATE_ROOT_PRIMARY = ".shipwright"
STATE_ROOT_LEGACY_CURSOR = ".cursor"
STATE_ROOT_LEGACY_SW = ".sw"

WORKFLOW_CONFIG_LEGACY_RELS: tuple[str, ...] = (
    f"{STATE_ROOT_LEGACY_CURSOR}/workflow.config.json",
    "workflow.config.json",
)
WORKFLOW_CONFIG_PREFERRED_REL = f"{STATE_ROOT_PRIMARY}/workflow.config.json"

HOST_BRAND_TOKENS: frozenset[str] = frozenset({"cursor", "claude"})


def workflow_config_candidates(root: Path) -> tuple[Path, ...]:
    """Ordered workflow configuration candidates (preferred first)."""
    return (
        root / WORKFLOW_CONFIG_PREFERRED_REL,
        *(root / rel for rel in WORKFLOW_CONFIG_LEGACY_RELS),
    )


def workflow_config_path(root: Path) -> Path | None:
    """Return the first existing workflow configuration file, if any."""
    for path in workflow_config_candidates(root):
        if path.is_file():
            return path
    return None


def workflow_config_write_path(root: Path) -> Path:
    """Preferred workflow configuration path for writes (may not exist yet)."""
    existing = workflow_config_path(root)
    if existing is not None:
        return existing
    return root / WORKFLOW_CONFIG_PREFERRED_REL


def load_workflow_config(root: Path) -> dict[str, Any]:
    """Load workflow configuration JSON from the resolved configuration path."""
    for path in workflow_config_candidates(root):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def _resolve_family(root: Path, preferred_rel: str, legacy_rels: tuple[str, ...]) -> Path:
    for rel in (preferred_rel, *legacy_rels):
        path = root / rel
        if path.exists():
            return path
    return root / preferred_rel


def _resolve_family_file(
    root: Path, preferred_rel: str, legacy_rels: tuple[str, ...]
) -> Path:
    for rel in (preferred_rel, *legacy_rels):
        path = root / rel
        if path.is_file():
            return path
    return root / preferred_rel


def deliver_runs_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/deliver-runs",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-deliver-runs",),
    )


def deliver_closeout_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/deliver-closeout",
        (f"{STATE_ROOT_LEGACY_SW}/deliver-closeout",),
    )


def deliver_locks_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/locks/deliver",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-deliver-locks",),
    )


def target_locks_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/locks/target",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-target-locks",),
    )


def doc_run_locks_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/locks/doc-run",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-doc-run-locks",),
    )


def doc_to_feature_handoff_locks_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/locks/doc-to-feature-handoff",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-doc-to-feature-handoff-locks",),
    )


def deliver_run_locks_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/locks/deliver-run",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-deliver-run-locks",),
    )


def living_docs_lock_path(root: Path) -> Path:
    return _resolve_family_file(
        root,
        f"{STATE_ROOT_PRIMARY}/locks/living-docs.lock",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-living-docs.lock",),
    )


def graph_cache_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/cache/graph",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-graph-cache",),
    )


def graph_runs_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/cache/graph-runs",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-graph-runs",),
    )


def hooks_state_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/cache/hooks-state",
        (f"{STATE_ROOT_LEGACY_CURSOR}/hooks/state",),
    )


def gate_cache_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/cache/gate",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-gate-cache",),
    )


def memory_rules_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/memory/rules",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-memory/rules",),
    )


def memory_bodies_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/memory",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-memory",),
    )


def memory_rule_allowlist_path(root: Path) -> Path:
    return _resolve_family_file(
        root,
        f"{STATE_ROOT_PRIMARY}/memory/rule-allowlist.json",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-memory-rule-allowlist.json",),
    )


def memory_provider_marker_path(root: Path) -> Path:
    return _resolve_family_file(
        root,
        f"{STATE_ROOT_PRIMARY}/memory/provider.marker",
        (
            f"{STATE_ROOT_LEGACY_CURSOR}/sw-memory.provider",
            "sw-memory.provider",
        ),
    )


def template_overrides_dir(root: Path) -> Path:
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/templates",
        (f"{STATE_ROOT_LEGACY_SW}/templates",),
    )


def sw_reference_operator_dir(root: Path) -> Path:
    """Operator-edited sw-reference inputs (schema, layout contract, etc.)."""
    return _resolve_family(
        root,
        f"{STATE_ROOT_PRIMARY}/sw-reference",
        (f"{STATE_ROOT_LEGACY_SW}",),
    )


def worktree_state_path(root: Path) -> Path:
    return _resolve_family_file(
        root,
        f"{STATE_ROOT_PRIMARY}/worktree-state.json",
        (f"{STATE_ROOT_LEGACY_CURSOR}/sw-worktree-state.json",),
    )


INVENTORY_ACCESSORS: dict[str, Callable[[Path], Path]] = {
    "workflow_config_path": workflow_config_path,
    "deliver_runs_dir": deliver_runs_dir,
    "deliver_closeout_dir": deliver_closeout_dir,
    "deliver_locks_dir": deliver_locks_dir,
    "target_locks_dir": target_locks_dir,
    "doc_run_locks_dir": doc_run_locks_dir,
    "doc_to_feature_handoff_locks_dir": doc_to_feature_handoff_locks_dir,
    "deliver_run_locks_dir": deliver_run_locks_dir,
    "living_docs_lock_path": living_docs_lock_path,
    "graph_cache_dir": graph_cache_dir,
    "graph_runs_dir": graph_runs_dir,
    "hooks_state_dir": hooks_state_dir,
    "gate_cache_dir": gate_cache_dir,
    "memory_rules_dir": memory_rules_dir,
    "memory_bodies_dir": memory_bodies_dir,
    "memory_rule_allowlist_path": memory_rule_allowlist_path,
    "memory_provider_marker_path": memory_provider_marker_path,
    "template_overrides_dir": template_overrides_dir,
    "sw_reference_operator_dir": sw_reference_operator_dir,
    "worktree_state_path": worktree_state_path,
}


def inventory_accessor(name: str) -> Callable[[Path], Path]:
    try:
        return INVENTORY_ACCESSORS[name]
    except KeyError as exc:
        raise KeyError(f"unknown inventory accessor: {name}") from exc


def path_matches_inventory_entry(resolved: Path, root: Path, entry: dict[str, Any]) -> bool:
    """True when *resolved* is under the entry's preferred or legacy path."""
    resolved_posix = resolved.resolve().as_posix()
    for key in ("newPath", "legacyPath"):
        rel = str(entry.get(key) or "").strip().rstrip("/")
        if not rel:
            continue
        candidate = (root / rel).resolve().as_posix()
        if resolved_posix == candidate or resolved_posix.startswith(candidate + "/"):
            return True
    return False
