#!/usr/bin/env python3
"""Crash/replay fixture harness for receipt-driven WorkflowGraph resume."""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from graph.convergence_loop import (
    ConvergenceBudgets,
    Finding,
    run_convergence_loop,
)
from graph.execution_receipts import ExecutionReceiptJournal
from graph.resource_pools import ResourcePoolRegistry
from graph.scheduler import GraphScheduler, NodeExecutionResult, SchedulerRun


class InjectedCrash(RuntimeError):
    """Intentional fixture interruption at a declared durable boundary."""


class CrashPoint(str, Enum):
    MID_NODE = "mid-node"
    MID_BARRIER = "mid-barrier"
    MID_LOOP = "mid-loop"


@dataclass(frozen=True)
class ReplayReport:
    crash_point: CrashPoint
    resumed: bool
    verdict: str
    duplicate_side_effects: tuple[str, ...]
    side_effect_counts: Mapping[str, int]
    replayed_nodes: tuple[str, ...]
    dispatched_nodes: tuple[str, ...]
    chat_history_used: bool
    scheduler_run: SchedulerRun


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


class _SideEffectLedger:
    """Fixture model of an idempotency-aware external side-effect boundary."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _load(self) -> dict[str, int]:
        if not self.path.is_file():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or any(
            not isinstance(key, str)
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count < 1
            for key, count in value.items()
        ):
            raise RuntimeError("side-effect ledger is corrupt")
        return value

    def apply_once(self, key: str) -> bool:
        values = self._load()
        if key in values:
            return False
        values[key] = 1
        _atomic_json(self.path, values)
        return True

    def counts(self) -> dict[str, int]:
        return self._load()


class _FingerprintFile:
    """Durable fingerprint-only store used by the convergence replay fixture."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self, namespace: str) -> tuple[str, ...]:
        if not self.path.is_file():
            return ()
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("fingerprint fixture state is corrupt")
        fingerprints = value.get(namespace, [])
        if not isinstance(fingerprints, list):
            raise RuntimeError("fingerprint fixture namespace is corrupt")
        return tuple(str(item) for item in fingerprints)

    def save(self, namespace: str, fingerprints: Any) -> None:
        value: dict[str, list[str]] = {}
        if self.path.is_file():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise RuntimeError("fingerprint fixture state is corrupt")
            value = loaded
        value[namespace] = sorted(set(str(item) for item in fingerprints))
        _atomic_json(self.path, value)


class CrashReplayHarness:
    """Inject one crash, restart with no transient context, and verify replay."""

    def __init__(
        self,
        graph: Mapping[str, Any],
        *,
        root: str | Path,
        kernel_options: Mapping[str, Any] | None = None,
    ) -> None:
        self.graph = graph
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.kernel_options = dict(kernel_options or {})
        self.receipts = ExecutionReceiptJournal(self.root / "receipts")
        self.effects = _SideEffectLedger(self.root / "side-effects.json")
        self.fingerprints = _FingerprintFile(self.root / "loop-fingerprints.json")

    def run(self, crash_point: CrashPoint, *, run_id: str) -> ReplayReport:
        fired = False
        dispatched: list[str] = []

        def execute(node: dict[str, Any]) -> NodeExecutionResult:
            nonlocal fired
            node_id = str(node["id"])
            kind = str(node["kind"])
            dispatched.append(node_id)
            if crash_point is CrashPoint.MID_BARRIER and kind == "barrier" and not fired:
                fired = True
                raise InjectedCrash(f"fixture crash before barrier {node_id}")
            effect_key = f"{run_id}:{node_id}:effect"
            self.effects.apply_once(effect_key)
            if crash_point is CrashPoint.MID_NODE and kind == "command" and not fired:
                fired = True
                raise InjectedCrash(f"fixture crash after side effect in {node_id}")
            return NodeExecutionResult(
                verdict="pass",
                output={"node": node_id},
                model="crash-replay-fixture",
                coverage={"resumedWithoutChat": True},
            )

        def execute_loop(
            node: dict[str, Any],
            bounds: Mapping[str, int],
        ) -> NodeExecutionResult:
            nonlocal fired
            node_id = str(node["id"])
            dispatched.append(node_id)
            namespace = f"{run_id}:{node_id}"

            def discover(_round: int, seen: frozenset[str]) -> list[Finding]:
                nonlocal fired
                if seen:
                    if crash_point is CrashPoint.MID_LOOP and not fired:
                        fired = True
                        raise InjectedCrash(f"fixture crash during loop {node_id}")
                    return []
                self.effects.apply_once(f"{namespace}:finding")
                return [Finding({"fixture": node_id}, tokens=1)]

            result = run_convergence_loop(
                namespace,
                discover,
                budgets=ConvergenceBudgets(
                    max_rounds=int(bounds["maxRounds"]),
                    max_findings=int(bounds.get("maxFindings", 10)),
                    max_tokens=int(bounds["maxTokens"]),
                ),
                fingerprint_store=self.fingerprints,
            )
            return NodeExecutionResult(
                verdict="pass" if result.converged else "fail",
                output={"fingerprints": list(result.fingerprints)},
                model="crash-replay-fixture",
                tokens=result.tokens_used,
                coverage={"rounds": len(result.rounds), "resumedWithoutChat": True},
            )

        def scheduler() -> GraphScheduler:
            return GraphScheduler(
                execute,
                receipts=self.receipts,
                pools=ResourcePoolRegistry(),
                convergence_executor=execute_loop,
            )

        try:
            scheduler().run(
                self.graph,
                run_id=run_id,
                internal_only=True,
                kernel_options=self.kernel_options,
            )
        except InjectedCrash:
            pass
        else:
            raise AssertionError(f"crash point {crash_point.value} was not reached")

        result = scheduler().run(
            self.graph,
            run_id=run_id,
            internal_only=True,
            kernel_options=self.kernel_options,
        )
        counts = self.effects.counts()
        duplicates = tuple(sorted(key for key, count in counts.items() if count != 1))
        replayed = tuple(node.node_id for node in result.nodes if not node.dispatched)
        return ReplayReport(
            crash_point=crash_point,
            resumed=True,
            verdict=result.verdict,
            duplicate_side_effects=duplicates,
            side_effect_counts=counts,
            replayed_nodes=replayed,
            dispatched_nodes=tuple(dispatched),
            chat_history_used=False,
            scheduler_run=result,
        )
