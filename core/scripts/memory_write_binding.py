#!/usr/bin/env python3
"""Per-repo memory write binding assert (PRD 279 R9/R11/R15/R16).

Executable chokepoint invoked immediately before provider dispatch for mutating
memory callers. Unbound writes refuse closed with a typed reason and a
secret-safe audit event. Does not authorize reads/preflight display paths.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config
from memory_lib import memory_section
from memory_redact import redact

IN_REPO_PROVIDER = "in-repo"
GLOBAL_PROJECT = "__global__"
MARKER_REL = ".cursor/sw-memory.provider"
_MARKER_PATHS = (".cursor/sw-memory.provider", "sw-memory.provider")


def _read_marker_raw(root: Path) -> str | None:
    """Read marker text without catalog validation (write-binding needs literal in-repo)."""
    for rel in _MARKER_PATHS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value or None
    return None

# Typed refuse causes — stable operator-facing identifiers (R16).
CAUSE_UNBOUND = "memory-write-unbound"
CAUSE_MARKER_REMOTE_NEEDS_PROJECT = "memory-write-marker-remote-needs-project"
CAUSE_GLOBAL_REFUSED = "memory-write-global-refused"
CAUSE_PROJECT_MISSING = "memory-write-project-missing"

_SECRETISH = re.compile(
    r"(?i)(token|secret|password|credential|api[_-]?key|authorization|bearer)"
)


@dataclass(frozen=True)
class MemoryWriteBinding:
    """Resolved write binding when assert passes."""

    provider: str
    project: str
    source: str  # "config" | "marker-in-repo"


@dataclass(frozen=True)
class MemoryWriteRefuse:
    """Typed refuse payload when assert fails."""

    cause: str
    reason: str
    operation: str
    category: str | None
    repo_path: str


class MemoryWriteBindingError(Exception):
    """Raised when a mutating memory write is refused."""

    def __init__(self, refuse: MemoryWriteRefuse) -> None:
        super().__init__(refuse.reason)
        self.refuse = refuse


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _canonical_repo_path(root: Path) -> str:
    try:
        return str(root.resolve())
    except OSError:
        return str(root)


def _basename_project(root: Path) -> str:
    name = root.name.strip()
    return name or "unnamed-repo"


def _sanitize_reason(text: str) -> str:
    """Scrub credential-ish substrings from refuse reasons (R16)."""
    scrubbed = _SECRETISH.sub("[redacted]", text)
    try:
        return redact(scrubbed, destination="logs")
    except Exception:
        return scrubbed


def _audit_path(root: Path) -> Path:
    return root / ".cursor" / "sw-memory-write-audit.jsonl"


def emit_write_refuse_audit(
    root: Path,
    *,
    operation: str,
    reason: str,
    cause: str,
    category: str | None = None,
) -> dict[str, Any]:
    """Append a structured refuse audit event (R15)."""
    event = {
        "event": "memory-write-refused",
        "timestamp": utc_now(),
        "repoPath": _sanitize_reason(_canonical_repo_path(root)),
        "operation": str(operation),
        "category": category,
        "cause": cause,
        "reason": _sanitize_reason(reason),
    }
    path = _audit_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError:
        # Audit is best-effort; refuse still stands.
        pass
    return event


def resolve_write_binding(root: Path, cfg: dict[str, Any] | None = None) -> MemoryWriteBinding | None:
    """Resolve an explicit write binding, or None when unbound.

    Binding is either:
    - config ``memory.provider`` + non-empty ``memory.project``, or
    - marker ``.cursor/sw-memory.provider`` with literal ``in-repo``
      (project derived from repository basename only).
    """
    config = cfg if cfg is not None else load_workflow_config(root)
    memory = memory_section(config)
    provider = str(memory.get("provider") or "").strip()
    project = str(memory.get("project") or "").strip()

    if provider and project:
        return MemoryWriteBinding(provider=provider, project=project, source="config")

    if provider and not project:
        # Config provider without project is not a complete binding (R11).
        return None

    raw_marker = _read_marker_raw(root)
    if raw_marker == IN_REPO_PROVIDER:
        return MemoryWriteBinding(
            provider=IN_REPO_PROVIDER,
            project=_basename_project(root),
            source="marker-in-repo",
        )
    if raw_marker and raw_marker != IN_REPO_PROVIDER:
        # Marker naming a remote/external provider without config project → unbound.
        return None
    return None


def _refuse(
    root: Path,
    *,
    operation: str,
    category: str | None,
    cause: str,
    reason: str,
) -> MemoryWriteRefuse:
    safe_reason = _sanitize_reason(reason)
    refuse = MemoryWriteRefuse(
        cause=cause,
        reason=safe_reason,
        operation=str(operation),
        category=category,
        repo_path=_canonical_repo_path(root),
    )
    emit_write_refuse_audit(
        root,
        operation=operation,
        reason=safe_reason,
        cause=cause,
        category=category,
    )
    return refuse


def assert_memory_write_binding(
    root: Path,
    operation: str,
    category: str | None = None,
    *,
    cfg: dict[str, Any] | None = None,
    project_override: str | None = None,
) -> MemoryWriteBinding:
    """Assert an explicit per-repo write binding before provider dispatch (R9).

    Returns the resolved binding on success. On refuse: emits audit (R15) and
    either raises ``MemoryWriteBindingError`` or returns via exception only —
    callers must not dispatch when this fails.
    """
    binding = resolve_write_binding(root, cfg)
    override = str(project_override).strip() if project_override is not None else None

    if binding is None:
        config = cfg if cfg is not None else load_workflow_config(root)
        memory = memory_section(config)
        provider = str(memory.get("provider") or "").strip()
        raw_marker = _read_marker_raw(root)
        if override == GLOBAL_PROJECT:
            refuse = _refuse(
                root,
                operation=operation,
                category=category,
                cause=CAUSE_GLOBAL_REFUSED,
                reason=(
                    f"{GLOBAL_PROJECT} writes require an explicit config binding "
                    "(memory.provider + memory.project=__global__); unbound refuses"
                ),
            )
        elif raw_marker and raw_marker != IN_REPO_PROVIDER:
            refuse = _refuse(
                root,
                operation=operation,
                category=category,
                cause=CAUSE_MARKER_REMOTE_NEEDS_PROJECT,
                reason=(
                    f"marker {MARKER_REL} selects provider {raw_marker!r}; "
                    "remote/external providers require explicit memory.project in config"
                ),
            )
        elif provider and not str(memory.get("project") or "").strip():
            refuse = _refuse(
                root,
                operation=operation,
                category=category,
                cause=CAUSE_PROJECT_MISSING,
                reason=(
                    f"memory.provider is set to {provider!r} but memory.project is empty; "
                    "remote/external providers require an explicit non-empty project"
                ),
            )
        else:
            refuse = _refuse(
                root,
                operation=operation,
                category=category,
                cause=CAUSE_UNBOUND,
                reason=(
                    "repository has no explicit memory write binding; set "
                    "memory.provider + memory.project in workflow.config.json, or place "
                    f"{MARKER_REL} with literal 'in-repo'"
                ),
            )
        raise MemoryWriteBindingError(refuse)

    effective_project = override if override is not None else binding.project
    if not effective_project:
        refuse = _refuse(
            root,
            operation=operation,
            category=category,
            cause=CAUSE_PROJECT_MISSING,
            reason="write project is empty after binding resolution",
        )
        raise MemoryWriteBindingError(refuse)

    # __global__ is explicit-only and never an ambient unbound default (Security).
    if effective_project == GLOBAL_PROJECT and binding.source != "config":
        refuse = _refuse(
            root,
            operation=operation,
            category=category,
            cause=CAUSE_GLOBAL_REFUSED,
            reason=(
                f"{GLOBAL_PROJECT} writes require an explicit config binding "
                "(memory.provider + memory.project); marker/unbound paths refuse"
            ),
        )
        raise MemoryWriteBindingError(refuse)

    if override is not None and effective_project != binding.project:
        # Allow explicit __global__ only under a config binding.
        if effective_project == GLOBAL_PROJECT and binding.source == "config":
            return MemoryWriteBinding(
                provider=binding.provider,
                project=GLOBAL_PROJECT,
                source=binding.source,
            )
        refuse = _refuse(
            root,
            operation=operation,
            category=category,
            cause=CAUSE_GLOBAL_REFUSED
            if effective_project == GLOBAL_PROJECT
            else CAUSE_UNBOUND,
            reason=(
                f"project override {effective_project!r} does not match bound "
                f"memory.project {binding.project!r}"
            ),
        )
        raise MemoryWriteBindingError(refuse)

    return binding


def binding_or_refuse_dict(
    root: Path,
    operation: str,
    category: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """JSON-friendly assert result for CLI/tests."""
    try:
        binding = assert_memory_write_binding(
            root, operation, category, **kwargs
        )
        return {
            "verdict": "pass",
            "action": "assert-memory-write-binding",
            "provider": binding.provider,
            "project": binding.project,
            "source": binding.source,
            "operation": operation,
            "category": category,
        }
    except MemoryWriteBindingError as exc:
        refuse = exc.refuse
        return {
            "verdict": "fail",
            "action": "assert-memory-write-binding",
            "halt": refuse.cause,
            "cause": refuse.cause,
            "reason": refuse.reason,
            "operation": refuse.operation,
            "category": refuse.category,
            "repoPath": refuse.repo_path,
        }


def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Assert per-repo memory write binding (PRD 279)")
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--category", default=None)
    parser.add_argument("--project", default=None, help="Optional project override (e.g. __global__)")
    args = parser.parse_args()
    root = (args.root or Path.cwd()).resolve()
    payload = binding_or_refuse_dict(
        root,
        args.operation,
        args.category,
        project_override=args.project,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    sys.exit(0 if payload.get("verdict") == "pass" else 20)


if __name__ == "__main__":
    main()
