#!/usr/bin/env python3
"""Realized-diff re-detect at integration barriers and merge gate (PRD 272 R4)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from graph.detectors.registry import CAPABILITY_MIGRATION
from graph.detectors.result import union_required_capability_ids
from graph.detectors.runner import run_detectors


@dataclass(frozen=True)
class RequirementSetSnapshot:
    """Monotone requirement set bound to a realized diff digest."""

    required_capability_ids: frozenset[str]
    diff_digest: str
    changed_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requiredCapabilityIds": sorted(self.required_capability_ids),
            "diffDigest": self.diff_digest,
            "changedPaths": list(self.changed_paths),
        }


@dataclass(frozen=True)
class RedetectGateVerdict:
    """Outcome of comparing dispatched vs recomputed requirement sets."""

    verdict: str
    dispatched: RequirementSetSnapshot
    current: RequirementSetSnapshot
    added: frozenset[str]
    removed: frozenset[str]
    unsatisfied: frozenset[str]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "dispatched": self.dispatched.to_dict(),
            "current": self.current.to_dict(),
            "added": sorted(self.added),
            "removed": sorted(self.removed),
            "unsatisfied": sorted(self.unsatisfied),
            "reason": self.reason,
        }


def diff_digest(changed_paths: tuple[str, ...]) -> str:
    payload = json.dumps(sorted(changed_paths), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compute_requirement_set(
    changed_paths: tuple[str, ...],
    *,
    repo_root: Path | None = None,
) -> RequirementSetSnapshot:
    """Recompute required capabilities from the realized diff."""
    results, _coverage = run_detectors(changed_paths, repo_root=repo_root)
    caps = frozenset(union_required_capability_ids(results))
    return RequirementSetSnapshot(
        required_capability_ids=caps,
        diff_digest=diff_digest(changed_paths),
        changed_paths=changed_paths,
    )


def evaluate_redetect_gate(
    *,
    changed_paths: tuple[str, ...],
    dispatched: RequirementSetSnapshot,
    satisfied_capability_ids: frozenset[str],
    repo_root: Path | None = None,
    gate: str = "barrier",
) -> RedetectGateVerdict:
    """Compare recomputed requirements to the dispatched set (monotone add-only)."""
    current = compute_requirement_set(changed_paths, repo_root=repo_root)
    added = current.required_capability_ids - dispatched.required_capability_ids
    removed = dispatched.required_capability_ids - current.required_capability_ids
    if removed:
        return RedetectGateVerdict(
            verdict="fail",
            dispatched=dispatched,
            current=current,
            added=added,
            removed=removed,
            unsatisfied=frozenset(),
            reason=(
                f"{gate}: requirement reduction refused — "
                f"removed {sorted(removed)} (R4 monotone)"
            ),
        )
    unsatisfied = added - satisfied_capability_ids
    if unsatisfied:
        return RedetectGateVerdict(
            verdict="fail",
            dispatched=dispatched,
            current=current,
            added=added,
            removed=removed,
            unsatisfied=unsatisfied,
            reason=(
                f"{gate}: newly detected requirements {sorted(unsatisfied)} "
                "not satisfied by executed passing capability nodes"
            ),
        )
    merged = RequirementSetSnapshot(
        required_capability_ids=dispatched.required_capability_ids | added,
        diff_digest=current.diff_digest,
        changed_paths=current.changed_paths,
    )
    return RedetectGateVerdict(
        verdict="pass",
        dispatched=merged,
        current=current,
        added=added,
        removed=removed,
        unsatisfied=frozenset(),
        reason=f"{gate}: redetect gate pass",
    )


def merge_gate_redetect(
    *,
    changed_paths: tuple[str, ...],
    dispatched: RequirementSetSnapshot,
    satisfied_capability_ids: frozenset[str],
    repo_root: Path | None = None,
) -> RedetectGateVerdict:
    """Final merge-gate redetect before ready."""
    return evaluate_redetect_gate(
        changed_paths=changed_paths,
        dispatched=dispatched,
        satisfied_capability_ids=satisfied_capability_ids,
        repo_root=repo_root,
        gate="merge",
    )


def docs_only_paths() -> tuple[str, ...]:
    return ("docs/readme.md",)


def docs_only_then_migration_paths() -> tuple[str, ...]:
    """Fixture: docs-only dispatch whose execution introduces a migration."""
    return ("docs/readme.md", "db/migrations/002_add_users.sql")


def migration_capability_required(paths: tuple[str, ...]) -> bool:
    snapshot = compute_requirement_set(paths)
    return CAPABILITY_MIGRATION in snapshot.required_capability_ids
