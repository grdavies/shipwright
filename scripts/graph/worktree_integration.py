#!/usr/bin/env python3
"""Kernel-owned worktree integration barrier (PRD 271 R30)."""
from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from graph.isolation_policy import IsolationMode, IsolationPolicy, WriteScope

_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


class WorktreeIntegrationError(RuntimeError):
    """Raised when worktree completion metadata is invalid."""


@dataclass(frozen=True)
class WorktreeCompletionManifest:
    """Validated mutating worktree completion envelope (R30)."""

    base_sha: str
    head_sha: str
    manifest: Mapping[str, str]
    head_ref: str = ""
    verification: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IntegrationTransitionResult:
    """Outcome of one kernel-owned integration transition."""

    node_id: str
    verdict: str
    settled: bool
    reason: str
    conflict: bool = False


def requires_worktree_integration(
    policy: IsolationPolicy,
    *,
    mutating: bool,
) -> bool:
    """Return True when a node completion must pass through the integration barrier."""
    return (
        mutating
        and policy.mode == IsolationMode.WORKTREE
        and policy.write_scope == WriteScope.WORKTREE
    )


def validate_manifest(raw: Mapping[str, Any]) -> WorktreeCompletionManifest:
    """Validate base/head SHA, manifest, and verification metadata (R30)."""
    base_sha = str(raw.get("baseSha") or raw.get("base_sha") or "").strip().lower()
    head_sha = str(raw.get("headSha") or raw.get("head_sha") or "").strip().lower()
    head_ref = str(raw.get("headRef") or raw.get("head_ref") or "").strip()
    verification_raw = raw.get("verification") or {}
    manifest_raw = raw.get("manifest") or raw.get("artifactManifest") or {}

    if not _SHA_RE.match(base_sha):
        raise WorktreeIntegrationError(f"invalid baseSha: {base_sha!r}")
    if not _SHA_RE.match(head_sha):
        raise WorktreeIntegrationError(f"invalid headSha: {head_sha!r}")
    if not isinstance(manifest_raw, Mapping) or not manifest_raw:
        raise WorktreeIntegrationError("manifest must be a non-empty mapping")
    if not isinstance(verification_raw, Mapping):
        raise WorktreeIntegrationError("verification metadata must be a mapping")

    manifest: dict[str, str] = {}
    for path, value in manifest_raw.items():
        text_path = str(path).strip()
        text_value = str(value).strip()
        if not text_path or not text_value:
            raise WorktreeIntegrationError(
                f"invalid manifest entry: {path!r} -> {value!r}"
            )
        manifest[text_path] = text_value

    return WorktreeCompletionManifest(
        base_sha=base_sha,
        head_sha=head_sha,
        head_ref=head_ref,
        manifest=manifest,
        verification=dict(verification_raw),
    )


def extract_worktree_manifest(
    coverage: Mapping[str, Any] | None,
) -> WorktreeCompletionManifest | None:
    """Parse worktree integration metadata from node coverage."""
    if not coverage:
        return None
    raw = coverage.get("worktreeIntegration") or coverage.get("worktree_integration")
    if not isinstance(raw, Mapping):
        return None
    return validate_manifest(raw)


class WorktreeIntegrationBarrier:
    """Deterministic integration barrier for mutating worktree completions (R30)."""

    def __init__(
        self,
        source_order: Mapping[str, int],
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._source_order = source_order
        self._clock = clock or (lambda: 0.0)
        self._pending: dict[str, WorktreeCompletionManifest] = {}
        self._integrated_paths: dict[str, tuple[str, str]] = {}
        self._history: list[dict[str, Any]] = []

    @property
    def pending_node_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(self._pending, key=self._source_order.__getitem__)
        )

    @property
    def history(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._history)

    def enqueue(self, node_id: str, manifest: WorktreeCompletionManifest) -> None:
        if node_id in self._pending:
            raise WorktreeIntegrationError(
                f"duplicate pending integration for node {node_id}"
            )
        self._pending[node_id] = manifest

    def has_pending(self) -> bool:
        return bool(self._pending)

    def drain(self) -> tuple[IntegrationTransitionResult, ...]:
        """Integrate all pending completions in deterministic source order."""
        ordered = sorted(self._pending, key=self._source_order.__getitem__)
        results: list[IntegrationTransitionResult] = []
        for node_id in ordered:
            manifest = self._pending.pop(node_id)
            result = self._integrate_one(node_id, manifest)
            self._history.append(
                {
                    "nodeId": node_id,
                    "verdict": result.verdict,
                    "settled": result.settled,
                    "conflict": result.conflict,
                    "reason": result.reason,
                    "baseSha": manifest.base_sha,
                    "headSha": manifest.head_sha,
                    "manifestPaths": sorted(manifest.manifest),
                    "atMonotonic": self._clock(),
                }
            )
            results.append(result)
        return tuple(results)

    def _integrate_one(
        self,
        node_id: str,
        manifest: WorktreeCompletionManifest,
    ) -> IntegrationTransitionResult:
        for path in sorted(manifest.manifest):
            content_hash = manifest.manifest[path]
            existing = self._integrated_paths.get(path)
            if existing is not None:
                existing_hash, owner = existing
                if existing_hash != content_hash:
                    return IntegrationTransitionResult(
                        node_id=node_id,
                        verdict="fail",
                        settled=True,
                        reason=(
                            f"integration conflict on {path}: "
                            f"{owner} vs {node_id}"
                        ),
                        conflict=True,
                    )
                continue
            self._integrated_paths[path] = (content_hash, node_id)
        return IntegrationTransitionResult(
            node_id=node_id,
            verdict="pass",
            settled=True,
            reason="worktree integration settled",
            conflict=False,
        )


def barrier_blocks_successors(
    *,
    predecessors: Mapping[str, Sequence[str]],
    outcomes: Mapping[str, Any],
    pending_integration: Sequence[str],
) -> bool:
    """True when any predecessor is unsettled or awaiting integration."""
    pending = set(pending_integration)
    for node_id, expected in predecessors.items():
        for pred in expected:
            if pred in pending:
                return True
            outcome = outcomes.get(pred)
            if outcome is None:
                continue
            if not getattr(outcome, "settled", True):
                return True
    return False
