#!/usr/bin/env python3
"""Per-node isolation policy (PRD 092 R8; PRD 269 R14)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from collections.abc import Mapping
from typing import Any, Iterable


class IsolationMode(str, Enum):
    NONE = "none"
    PROCESS = "process"
    WORKTREE = "worktree"
    CONTAINER = "container"
    REMOTE = "remote"


class WriteScope(str, Enum):
    NONE = "none"
    READ_ONLY = "read-only"
    SCOPED = "scoped"
    WORKTREE = "worktree"


# Sentinel: mutating node with empty/unresolvable write set overlaps everything.
UNKNOWN_WRITE_PATH = "<<unknown-write-path>>"


@dataclass(frozen=True)
class IsolationPolicy:
    mode: IsolationMode
    write_scope: WriteScope = WriteScope.SCOPED

    def allows_concurrent_writers(self) -> bool:
        if self.write_scope in (WriteScope.NONE, WriteScope.READ_ONLY):
            return True
        return self.mode in (
            IsolationMode.WORKTREE,
            IsolationMode.CONTAINER,
            IsolationMode.REMOTE,
        )

    def is_mutating(self) -> bool:
        return self.write_scope not in (WriteScope.NONE, WriteScope.READ_ONLY)


@dataclass(frozen=True)
class ContentionFinding:
    node_a: str
    node_b: str
    path: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodeA": self.node_a,
            "nodeB": self.node_b,
            "path": self.path,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class NodeIsolationClaim:
    node_id: str
    policy: IsolationPolicy
    write_paths: frozenset[str]


def parse_isolation_policy(raw: dict[str, Any]) -> IsolationPolicy:
    mode = IsolationMode(str(raw.get("mode") or IsolationMode.NONE.value))
    scope = WriteScope(str(raw.get("writeScope") or WriteScope.SCOPED.value))
    return IsolationPolicy(mode=mode, write_scope=scope)


def normalize_write_path(path: str, *, root: Path | None = None) -> str:
    """Realpath-normalize a write path; keep UNKNOWN sentinel untouched."""
    if path == UNKNOWN_WRITE_PATH:
        return UNKNOWN_WRITE_PATH
    raw = str(path).strip()
    if not raw:
        return UNKNOWN_WRITE_PATH
    base = root or Path.cwd()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=False)
    except OSError:
        resolved = Path(os.path.normpath(str(candidate)))
    # Prefer repo-relative form when under root for stable comparisons.
    try:
        rel = resolved.relative_to(base.resolve(strict=False))
        text = rel.as_posix()
    except ValueError:
        text = resolved.as_posix()
    return text or UNKNOWN_WRITE_PATH


def normalize_write_paths(
    paths: Iterable[str], *, root: Path | None = None
) -> frozenset[str]:
    return frozenset(normalize_write_path(p, root=root) for p in paths)


def paths_overlap(a: str, b: str) -> bool:
    """True when paths are equal, alias, or one is an ancestor/prefix of the other."""
    if a == UNKNOWN_WRITE_PATH or b == UNKNOWN_WRITE_PATH:
        return True
    if a == b:
        return True
    a_parts = Path(a).parts
    b_parts = Path(b).parts
    # Prefix / ancestor containment (directory vs file).
    n = min(len(a_parts), len(b_parts))
    if n == 0:
        return False
    return a_parts[:n] == b_parts[:n] and (
        len(a_parts) == n or len(b_parts) == n
    )


def claim_write_set(claim: NodeIsolationClaim) -> frozenset[str]:
    """Effective write set: mutating + empty → unknown (overlaps everything)."""
    if not claim.policy.is_mutating():
        return frozenset()
    if not claim.write_paths:
        return frozenset({UNKNOWN_WRITE_PATH})
    normalized = normalize_write_paths(claim.write_paths)
    if not normalized or UNKNOWN_WRITE_PATH in normalized:
        return frozenset({UNKNOWN_WRITE_PATH})
    return normalized


def _pair_contends(a: NodeIsolationClaim, b: NodeIsolationClaim) -> list[ContentionFinding]:
    if (
        a.policy.write_scope == WriteScope.READ_ONLY
        or b.policy.write_scope == WriteScope.READ_ONLY
        or a.policy.write_scope == WriteScope.NONE
        or b.policy.write_scope == WriteScope.NONE
    ):
        # Read-only / none never contend on writes.
        if not a.policy.is_mutating() or not b.policy.is_mutating():
            return []

    if a.policy.allows_concurrent_writers() and b.policy.allows_concurrent_writers():
        if a.policy.mode not in (IsolationMode.NONE, IsolationMode.PROCESS) and b.policy.mode not in (
            IsolationMode.NONE,
            IsolationMode.PROCESS,
        ):
            return []

    set_a = claim_write_set(a)
    set_b = claim_write_set(b)
    findings: list[ContentionFinding] = []
    for path_a in sorted(set_a):
        for path_b in sorted(set_b):
            if not paths_overlap(path_a, path_b):
                continue
            path = (
                UNKNOWN_WRITE_PATH
                if UNKNOWN_WRITE_PATH in (path_a, path_b)
                else (path_a if path_a == path_b else f"{path_a}|{path_b}")
            )
            reason = (
                "unknown write path overlaps everything"
                if path == UNKNOWN_WRITE_PATH
                else "concurrent writers without sufficient isolation"
            )
            findings.append(
                ContentionFinding(
                    node_a=a.node_id,
                    node_b=b.node_id,
                    path=path,
                    reason=reason,
                )
            )
    return findings


def analyze_write_contention(claims: Iterable[NodeIsolationClaim]) -> list[ContentionFinding]:
    """Fail closed when concurrent writers share paths without sufficient isolation."""
    findings: list[ContentionFinding] = []
    items = list(claims)
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            findings.extend(_pair_contends(a, b))
    return findings


def contends_with_inflight(
    candidate: NodeIsolationClaim,
    inflight: Iterable[NodeIsolationClaim],
) -> list[ContentionFinding]:
    """Dispatch-gate helper: contention of candidate against the in-flight union."""
    findings: list[ContentionFinding] = []
    for other in inflight:
        findings.extend(_pair_contends(candidate, other))
    return findings


# Shadow dispatch (PRD 270 R2): read-only allowlist; mutating kinds estimated from receipts.
SHADOW_READ_ONLY_NODE_KINDS = frozenset(
    {"barrier", "gate", "router", "transform", "verifier"}
)
SHADOW_MUTATING_NODE_KINDS = frozenset({"command", "script", "convergence-loop"})
SHADOW_FORBIDDEN_STEP_TOKENS = (
    "credential-broker",
    "outbound-adapter",
    "write-isolation-lease",
)


@dataclass(frozen=True)
class ShadowDispatchDecision:
    """How shadow mode treats one node without mutating production dispatch."""

    node_id: str
    mode: str
    reason: str = ""


@dataclass(frozen=True)
class ShadowReceiptEstimate:
    """Receipt-backed estimate for a mutating node that shadow does not execute."""

    node_id: str
    duration_ms: int
    tokens: int
    cost: float


def _node_blob(node: Mapping[str, Any]) -> str:
    node_id = str(node.get("id") or "")
    step = str((node.get("target") or {}).get("step") or "")
    return f"{node_id} {step}"


def shadow_kind_is_mutating(kind: str) -> bool:
    """Unknown or newly added kinds are mutating; only the closed read-only set executes."""
    normalized = str(kind or "")
    if normalized in SHADOW_READ_ONLY_NODE_KINDS:
        return False
    return True


def shadow_node_is_analysis_labeled(node: Mapping[str, Any]) -> bool:
    """True when the node is explicitly labeled as analysis work."""
    blob = _node_blob(node).lower()
    return "analysis" in blob


def shadow_forbidden_capability_node(node: Mapping[str, Any]) -> bool:
    """Shadow holds no credential broker, outbound adapter, or write-isolation lease."""
    blob = _node_blob(node)
    return any(token in blob for token in SHADOW_FORBIDDEN_STEP_TOKENS)


def shadow_isolation_policy(node: Mapping[str, Any]) -> IsolationPolicy:
    """Shadow nodes use READ_ONLY or NONE isolation — never a write-scoped worktree."""
    if shadow_forbidden_capability_node(node):
        return IsolationPolicy(mode=IsolationMode.NONE, write_scope=WriteScope.NONE)
    if shadow_kind_is_mutating(str(node.get("kind") or "")):
        return IsolationPolicy(mode=IsolationMode.NONE, write_scope=WriteScope.NONE)
    return IsolationPolicy(mode=IsolationMode.PROCESS, write_scope=WriteScope.READ_ONLY)


def shadow_node_admissible(node: Mapping[str, Any]) -> tuple[bool, str]:
    """Fail closed when shadow would need credentials, adapters, or write leases."""
    if shadow_forbidden_capability_node(node):
        return False, "shadow forbids credential broker and outbound adapters"
    kind = str(node.get("kind") or "")
    if shadow_kind_is_mutating(kind):
        return True, ""
    isolation = node.get("isolation") or {}
    write_scope = str(isolation.get("writeScope") or WriteScope.NONE.value)
    mode = str(isolation.get("mode") or IsolationMode.NONE.value)
    if write_scope in {WriteScope.SCOPED.value, WriteScope.WORKTREE.value}:
        return False, "shadow forbids write-scoped worktree isolation"
    if mode == IsolationMode.WORKTREE.value:
        return False, "shadow forbids worktree isolation mode"
    return True, ""


def shadow_refuse_write_lease(node: Mapping[str, Any]) -> bool:
    """Mutating analysis nodes and all mutating kinds are refused a write lease."""
    kind = str(node.get("kind") or "")
    if shadow_kind_is_mutating(kind):
        return True
    if shadow_node_is_analysis_labeled(node):
        execution = node.get("execution") or {}
        if execution.get("purity") == "mutating":
            return True
        write_scope = str((node.get("isolation") or {}).get("writeScope") or "")
        if write_scope in {WriteScope.SCOPED.value, WriteScope.WORKTREE.value}:
            return True
    return False


def shadow_refuse_credential_resolution(node: Mapping[str, Any]) -> bool:
    """Shadow never resolves credentials — especially for mutating analysis nodes."""
    if shadow_forbidden_capability_node(node):
        return True
    if shadow_refuse_write_lease(node):
        return True
    return shadow_kind_is_mutating(str(node.get("kind") or ""))


def classify_shadow_dispatch(node: Mapping[str, Any]) -> ShadowDispatchDecision:
    """Classify whether shadow executes read-only work or estimates from receipts."""
    node_id = str(node.get("id") or "")
    kind = str(node.get("kind") or "")
    admissible, reason = shadow_node_admissible(node)
    if not admissible:
        return ShadowDispatchDecision(node_id, "refused", reason)
    if shadow_kind_is_mutating(kind):
        return ShadowDispatchDecision(
            node_id,
            "estimate-from-receipt",
            "mutating kind estimated from receipts",
        )
    return ShadowDispatchDecision(
        node_id,
        "execute-read-only",
        "read-only allowlist kind",
    )


def shadow_node_claim(node: Mapping[str, Any]) -> NodeIsolationClaim:
    """Effective isolation claim for shadow contention analysis."""
    return NodeIsolationClaim(
        node_id=str(node.get("id") or ""),
        policy=shadow_isolation_policy(node),
        write_paths=frozenset(),
    )


def estimate_mutating_from_receipt(
    node_id: str,
    receipt: Mapping[str, Any] | None,
    *,
    token_cost: float = 0.0,
) -> ShadowReceiptEstimate:
    """Estimate mutating-node cost/latency from a historical receipt."""
    if receipt is None:
        return ShadowReceiptEstimate(node_id=node_id, duration_ms=0, tokens=0, cost=0.0)
    tokens = int(receipt.get("tokens") or 0)
    duration_ms = int(receipt.get("durationMs") or 0)
    return ShadowReceiptEstimate(
        node_id=node_id,
        duration_ms=duration_ms,
        tokens=tokens,
        cost=float(tokens) * token_cost,
    )
