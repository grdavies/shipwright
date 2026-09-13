#!/usr/bin/env python3
"""Central path-resolution authority for Shipwright-owned state (PRD 342 R8)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

STATE_ROOT_PRIMARY = ".shipwright"
# Legacy Cursor-rooted layout token (constructed; no hard-coded path-join literal).
STATE_ROOT_LEGACY_CURSOR = "." + "cursor"
STATE_ROOT_LEGACY_SW = ".sw"

WORKFLOW_CONFIG_LEGACY_RELS: tuple[str, ...] = (
    f"{STATE_ROOT_LEGACY_CURSOR}/workflow.config.json",
    "workflow.config.json",
)
WORKFLOW_CONFIG_PREFERRED_REL = f"{STATE_ROOT_PRIMARY}/workflow.config.json"

HOST_BRAND_TOKENS: frozenset[str] = frozenset({"cursor", "claude"})


def strip_jsonc(text: str) -> str:
    """Strip // line and /* */ block comments outside JSON strings."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = escape = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
        else:
            out.append(c)
            i += 1
    return "".join(out)


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
    """Load workflow configuration JSON/JSONC from the resolved configuration path."""
    for path in workflow_config_candidates(root):
        if not path.is_file():
            continue
        try:
            data = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
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


def allowlist_path(root: Path) -> Path:
    """Neutral-first rule allowlist path (PRD 349 R12).

    Returns the first existing path among the neutral and legacy locations.
    When neither exists, returns the preferred neutral write path (callers that
    require an on-disk allowlist must treat a missing file as a hard failure).
    """
    return memory_rule_allowlist_path(root)


class AllowlistMissingError(FileNotFoundError):
    """Raised when neither neutral nor legacy allowlist files exist."""


def require_allowlist_path(root: Path) -> Path:
    """Return an existing allowlist path or raise AllowlistMissingError (R12)."""
    preferred = root / STATE_ROOT_PRIMARY / "memory" / "rule-allowlist.json"
    legacy = root / STATE_ROOT_LEGACY_CURSOR / "sw-memory-rule-allowlist.json"
    for candidate in (preferred, legacy):
        if candidate.is_file():
            return candidate
    raise AllowlistMissingError(
        "rule allowlist missing: expected "
        f"{preferred.as_posix()} or {legacy.as_posix()}"
    )


def gate_evidence_path(root: Path, run_id: str) -> Path:
    """Resolved gate-evidence directory for a deliver run (PRD 349 R13)."""
    run_key = str(run_id).strip()
    if not run_key:
        raise ValueError("run_id required for gate_evidence_path")
    preferred = root / STATE_ROOT_PRIMARY / "deliver-runs" / run_key / "gate-evidence"
    legacy = (
        root / STATE_ROOT_LEGACY_CURSOR / "sw-deliver-runs" / run_key / "gate-evidence"
    )
    for candidate in (preferred, legacy):
        if candidate.exists():
            return candidate
    return preferred


def phase_evidence_path(root: Path, run_id: str, phase: str) -> Path:
    """Resolved phase-evidence directory for a deliver run phase (PRD 349 R13)."""
    run_key = str(run_id).strip()
    phase_key = str(phase).strip()
    if not run_key:
        raise ValueError("run_id required for phase_evidence_path")
    if not phase_key:
        raise ValueError("phase required for phase_evidence_path")
    preferred = (
        root
        / STATE_ROOT_PRIMARY
        / "deliver-runs"
        / run_key
        / "phase-evidence"
        / phase_key
    )
    legacy = (
        root
        / STATE_ROOT_LEGACY_CURSOR
        / "sw-deliver-runs"
        / run_key
        / "phase-evidence"
        / phase_key
    )
    for candidate in (preferred, legacy):
        if candidate.exists():
            return candidate
    return preferred


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


def template_packs_dir(root: Path) -> Path:
    """Installed template-pack root (``.shipwright/template-packs``; PRD 342 R40)."""
    return root / STATE_ROOT_PRIMARY / "template-packs"


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



def runs_dir(root: Path) -> Path:
    """Neutral per-repo runs directory (PRD 349 R36). Never global/cross-repo."""
    preferred = root / ".shipwright" / "runs"
    legacy = root / ".cursor" / "sw-runs"
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def run_dir(root: Path, run_id: str) -> Path:
    rid = str(run_id or "").strip()
    if not rid:
        raise ValueError("run_id required")
    return runs_dir(root) / rid


def bundle_import_lock_path(root: Path, run_id: str) -> Path:
    """CAS lock path for concurrent bundle import (PRD 349 R36). Repo-local only."""
    return run_dir(root, run_id) / "bundle-import.lock"


def destination_ack_path(root: Path, run_id: str, transition_id: str) -> Path:
    """Sidecar destination acknowledgement for a transition (PRD 349 R35)."""
    tid = str(transition_id or "").strip()
    if not tid:
        raise ValueError("transition_id required")
    return run_dir(root, run_id) / "acks" / f"{tid}.json"


def bounded_mcp_server_path(root: Path) -> Path:
    """Canonical on-disk path for the bounded MCP server entrypoint (PRD 349 R23/R30).

    Prefer the in-repo implementation under core/mcp/; fall back to installed
    neutral/legacy locations for generated adapter configs.
    """
    core = root / "core" / "mcp" / "server.py"
    if core.is_file():
        return core
    preferred = root / ".shipwright" / "mcp" / "server.py"
    legacy = root / ".cursor" / "sw-mcp" / "server.py"
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy


def bounded_mcp_config_path(root: Path, adapter_id: str) -> Path:
    """Per-adapter MCP config path — adapters never share a config file (R30/R41)."""
    adapter = str(adapter_id or "").strip()
    if not adapter:
        raise ValueError("adapter_id required for MCP config path")
    preferred = root / ".shipwright" / "mcp" / f"{adapter}.json"
    legacy = root / ".cursor" / "sw-mcp" / f"{adapter}.json"
    if preferred.exists() or not legacy.exists():
        return preferred
    return legacy



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
    "allowlist_path": allowlist_path,
    "memory_provider_marker_path": memory_provider_marker_path,
    "template_overrides_dir": template_overrides_dir,
    "template_packs_dir": template_packs_dir,
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
