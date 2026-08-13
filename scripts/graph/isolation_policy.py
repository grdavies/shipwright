#!/usr/bin/env python3
"""Per-node isolation policy (PRD 092 R8)."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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


def analyze_write_contention(claims: Iterable[NodeIsolationClaim]) -> list[ContentionFinding]:
    """Fail closed when concurrent writers share paths without sufficient isolation."""
    findings: list[ContentionFinding] = []
    items = list(claims)
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            overlap = sorted(a.write_paths & b.write_paths)
            if not overlap:
                continue
            # Read-only peers never contend on writes
            if (
                a.policy.write_scope == WriteScope.READ_ONLY
                or b.policy.write_scope == WriteScope.READ_ONLY
            ):
                continue
            if a.policy.allows_concurrent_writers() and b.policy.allows_concurrent_writers():
                # Both isolated enough (e.g. distinct worktrees) — still flag same logical path
                # only when either side uses none/process (shared filesystem view).
                if a.policy.mode in (IsolationMode.NONE, IsolationMode.PROCESS) or b.policy.mode in (
                    IsolationMode.NONE,
                    IsolationMode.PROCESS,
                ):
                    pass
                else:
                    continue
            for path in overlap:
                findings.append(
                    ContentionFinding(
                        node_a=a.node_id,
                        node_b=b.node_id,
                        path=path,
                        reason="concurrent writers without sufficient isolation",
                    )
                )
    return findings
