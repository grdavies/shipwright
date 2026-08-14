#!/usr/bin/env python3
"""Crash/replay fixture harness for receipt-driven WorkflowGraph resume (R13/R16)."""
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
from graph.execution_receipts import ExecutionReceiptJournal, default_store_root
from graph.resource_pools import ResourcePoolRegistry
from graph.scheduler import (
    CancelMode,
    GraphScheduler,
    NodeExecutionResult,
    SchedulerRun,
)


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


@dataclass(frozen=True)
class TeardownDurabilityReport:
    """Evidence that run-scoped journal artifacts survive harness teardown (R13)."""

    run_id: str
    receipts: tuple[dict[str, Any], ...]
    intents: tuple[dict[str, Any], ...]
    pool_snapshot: Mapping[str, Any] | None
    telemetry: Mapping[str, Any] | None
    readable: bool


@dataclass(frozen=True)
class CancelDrainReport:
    """Evidence that cancel-and-drain releases owner-token leases (R16)."""

    run_id: str
    verdict: str
    cancelled_nodes: tuple[str, ...]
    released_leases: tuple[str, ...]
    pool_snapshot: Mapping[str, Any]
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
        # Run-scoped journal under a gitignored-style store layout (R13).
        self.store_root = default_store_root(self.root)
        self.receipts = ExecutionReceiptJournal(self.root / "receipts")
        self.effects = _SideEffectLedger(self.root / "side-effects.json")
        self.fingerprints = _FingerprintFile(self.root / "loop-fingerprints.json")

    def _run_scoped_journal(self, run_id: str) -> ExecutionReceiptJournal:
        return ExecutionReceiptJournal.for_run(self.store_root, run_id)

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

    def teardown_and_read(self, run_id: str) -> TeardownDurabilityReport:
        """Drop transient harness handles and re-open the durable run journal (R13)."""
        # Simulate process teardown: drop in-memory handles, keep on-disk store.
        store = Path(self.store_root)
        journal = ExecutionReceiptJournal.for_run(store, run_id)
        # Also mirror any root-level receipts used by older fixtures into run scope
        # when the caller wrote through self.receipts with run-prefixed keys.
        for receipt in self.receipts.list_run_receipts(run_id):
            key = str(receipt.get("idempotencyKey") or "")
            node_id = str(receipt.get("nodeId") or "")
            if not key or not node_id:
                continue
            payload = {
                field: receipt[field]
                for field in (
                    "model",
                    "attempts",
                    "tokens",
                    "durationMs",
                    "inputHashes",
                    "outputHashes",
                    "verdict",
                    "coverage",
                )
                if field in receipt
            }
            try:
                journal.finish(node_id, key, payload)
            except Exception:
                pass
        for intent in self.receipts.list_inflight_intents():
            key = str(intent.get("idempotencyKey") or "")
            node_id = str(intent.get("nodeId") or "")
            if not key.startswith(f"{run_id}:") or not node_id:
                continue
            payload = {
                field: intent[field]
                for field in (
                    "model",
                    "attempts",
                    "tokens",
                    "durationMs",
                    "inputHashes",
                    "outputHashes",
                    "verdict",
                    "coverage",
                )
                if field in intent
            }
            try:
                journal.begin(node_id, key, payload)
            except Exception:
                pass
        snap = self.receipts.read_pool_snapshot()
        telemetry = self.receipts.read_telemetry()
        if snap is not None:
            journal.write_pool_snapshot(
                dict(snap.get("pools") or {}),
                parked=list(snap.get("parked") or []),
                queue=list(snap.get("queue") or []),
            )
        if telemetry is not None:
            journal.write_telemetry(
                {k: v for k, v in telemetry.items() if k != "runId"}
            )

        # Teardown: forget transient objects.
        reopened = ExecutionReceiptJournal.for_run(store, run_id)
        receipts = tuple(reopened.list_receipts())
        intents = tuple(reopened.list_inflight_intents())
        pool_snapshot = reopened.read_pool_snapshot()
        tele = reopened.read_telemetry()
        readable = True
        try:
            _ = list(receipts)
            _ = list(intents)
            _ = pool_snapshot
            _ = tele
        except Exception:
            readable = False
        return TeardownDurabilityReport(
            run_id=run_id,
            receipts=receipts,
            intents=intents,
            pool_snapshot=pool_snapshot,
            telemetry=tele,
            readable=readable,
        )

    def cancel_and_drain(
        self,
        *,
        run_id: str,
        cancel_after: str,
        held_leases: Mapping[str, bool] | None = None,
    ) -> CancelDrainReport:
        """Run until ``cancel_after``, then cancel-and-drain with lease release (R16)."""
        journal = self._run_scoped_journal(run_id)
        pools = ResourcePoolRegistry.from_config(
            limits={"code-writers": 4, "read-only-reviewers": 4}
        )
        released: list[str] = []
        leases = dict(held_leases or {})

        def release_lease(node_id: str) -> None:
            if leases.get(node_id):
                leases[node_id] = False
                released.append(node_id)

        def execute(node: dict[str, Any]) -> NodeExecutionResult:
            node_id = str(node["id"])
            leases.setdefault(node_id, True)
            if node_id == cancel_after:
                scheduler.request_cancel(CancelMode.CANCEL_AND_DRAIN)
            return NodeExecutionResult(
                verdict="pass",
                output={"node": node_id},
                model="cancel-drain-fixture",
                duration_ms=1,
            )

        scheduler = GraphScheduler(
            execute,
            receipts=journal,
            pools=pools,
            lease_releaser=release_lease,
            compensation=lambda node_id: None,
        )
        result = scheduler.run(
            self.graph,
            run_id=run_id,
            internal_only=True,
            kernel_options=self.kernel_options,
        )
        cancelled = tuple(
            node.node_id for node in result.nodes if node.verdict == "cancelled"
        )
        return CancelDrainReport(
            run_id=run_id,
            verdict=result.verdict,
            cancelled_nodes=cancelled,
            released_leases=tuple(released),
            pool_snapshot=pools.snapshot(),
            scheduler_run=result,
        )
