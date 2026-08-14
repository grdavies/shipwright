#!/usr/bin/env python3
"""Read-only, receipts-backed observability for graph runs (PRD 269 R10/R11)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from graph.cost_telemetry import observability_fields
from graph.execution_receipts import ExecutionReceiptJournal

READ_ONLY_COMMANDS = frozenset({"status", "show", "explain", "critical-path", "live"})
MUTATING_COMMANDS = frozenset({"retry", "replay"})

# Mutually exclusive live node states (R11), ordered for legend / stable display.
LIVE_STATES = (
    "completed",
    "cached/skipped",
    "failed",
    "retrying",
    "running",
    "dependency-blocked",
    "pool-queued",
    "awaiting-human-gate",
)

# Blocker hierarchy: actionable first, then passive waits (R11).
BLOCKER_KIND_ORDER = (
    "failed-predecessor",
    "human-gate",
    "pool-capacity",
    "dependency",
    "unknown",
)

STATE_LEGEND = {
    "completed": "node finished with a passing receipt",
    "cached/skipped": "content-addressed reuse or explicit skip",
    "failed": "terminal fail verdict",
    "retrying": "in-flight after a prior attempt",
    "running": "pre-dispatch intent or active execution",
    "dependency-blocked": "waiting on unsettled predecessors",
    "pool-queued": "ready but waiting on pool / park queue",
    "awaiting-human-gate": "paused for human confirmation or merge gate",
}


class ObservabilityError(ValueError):
    """Raised when graph evidence or an observability request is invalid."""


@dataclass(frozen=True)
class CriticalPathNode:
    node_id: str
    cumulative_duration_ms: int


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _receipt_sort_key(receipt: Mapping[str, Any]) -> tuple[int, int, int]:
    """Prefer newer / richer receipts when duplicates collide for one node."""
    attempts = _as_int(receipt.get("attempts"), 0)
    duration = _as_int(receipt.get("durationMs"), 0)
    state_rank = 1 if receipt.get("state") == "complete" else 0
    return (state_rank, attempts, duration)


def _receipt_index(
    receipts: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index receipts by nodeId; duplicate receipts degrade per-node (R11)."""
    indexed: dict[str, dict[str, Any]] = {}
    degraded: dict[str, dict[str, Any]] = {}
    for receipt in receipts:
        node_id = receipt.get("nodeId")
        if not isinstance(node_id, str) or not node_id:
            raise ObservabilityError("receipt is missing nodeId")
        payload = dict(receipt)
        if node_id not in indexed:
            indexed[node_id] = payload
            continue
        existing = indexed[node_id]
        winner = (
            payload
            if _receipt_sort_key(payload) >= _receipt_sort_key(existing)
            else existing
        )
        loser = existing if winner is payload else payload
        indexed[node_id] = winner
        prior = degraded.get(node_id, {"nodeId": node_id, "duplicateCount": 1})
        degraded[node_id] = {
            "nodeId": node_id,
            "duplicateCount": int(prior.get("duplicateCount", 1)) + 1,
            "keptIdempotencyKey": winner.get("idempotencyKey"),
            "droppedIdempotencyKey": loser.get("idempotencyKey"),
            "degraded": True,
        }
    return indexed, degraded


def _node_specs(graph: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    try:
        nodes = graph["spec"]["nodes"]
    except (KeyError, TypeError) as exc:
        raise ObservabilityError("invalid WorkflowGraph evidence") from exc
    return {str(node["id"]): dict(node) for node in nodes}


def _declared_duration_hint_ms(node: Mapping[str, Any]) -> int | None:
    """Declared node duration hint (ms), if present on the node or resources."""
    for key in ("durationHintMs", "estimatedDurationMs"):
        if key in node and node[key] is not None:
            value = _as_int(node.get(key), -1)
            return value if value >= 0 else None
    resources = node.get("resources")
    if isinstance(resources, Mapping):
        for key in ("durationHintMs", "estimatedDurationMs"):
            if key in resources and resources[key] is not None:
                value = _as_int(resources.get(key), -1)
                return value if value >= 0 else None
    return None


def _node_model_estimate(node: Mapping[str, Any]) -> str:
    execution = node.get("execution") if isinstance(node.get("execution"), Mapping) else {}
    for key in ("model", "modelTier", "tier"):
        value = node.get(key) or execution.get(key)
        if isinstance(value, str) and value:
            return value
    kind = str(node.get("kind") or "command")
    if kind in {"verifier", "review", "judgment"}:
        return "deep"
    if kind in {"transform", "router"}:
        return "cheap"
    return "build"


def _is_human_gate_node(node: Mapping[str, Any]) -> bool:
    kind = str(node.get("kind") or "")
    if kind in {"human-gate", "human-merge-gate", "await-human"}:
        return True
    target = node.get("target")
    if isinstance(target, Mapping):
        step = str(target.get("step") or "")
        if "human" in step.lower() and "gate" in step.lower():
            return True
    coverage = node.get("coverage") if isinstance(node.get("coverage"), Mapping) else {}
    return bool(node.get("humanMergeGate") or coverage.get("awaitingHumanGate"))


class GraphObservability:
    """Query immutable graph, receipt, and in-flight snapshots without dispatching work."""

    def __init__(
        self,
        graph: Mapping[str, Any],
        receipts: Iterable[Mapping[str, Any]],
        *,
        run_id: str = "",
        inflight: Iterable[Mapping[str, Any]] | None = None,
        pool_snapshot: Mapping[str, Any] | None = None,
        estimated_durations: Mapping[str, int] | None = None,
        graph_hash: str = "",
    ) -> None:
        self._graph = graph
        self._run_id = run_id
        self._graph_hash = graph_hash
        self._receipts, self._degraded = _receipt_index(receipts)
        self._inflight = {
            str(item["nodeId"]): dict(item)
            for item in (inflight or ())
            if isinstance(item, Mapping) and isinstance(item.get("nodeId"), str)
        }
        self._pool_snapshot = dict(pool_snapshot) if pool_snapshot else {}
        self._estimated_durations = {
            str(node_id): max(0, int(duration))
            for node_id, duration in (estimated_durations or {}).items()
        }
        try:
            nodes = graph["spec"]["nodes"]
            edges = graph["spec"]["edges"]
        except (KeyError, TypeError) as exc:
            raise ObservabilityError("invalid WorkflowGraph evidence") from exc
        self._nodes = _node_specs(graph)
        self._node_ids = tuple(str(node["id"]) for node in nodes)
        self._edges = tuple((str(edge["from"]), str(edge["to"])) for edge in edges)
        self._predecessors = {
            node_id: sorted(source for source, target in self._edges if target == node_id)
            for node_id in self._node_ids
        }
        self._successors = {
            node_id: sorted(target for source, target in self._edges if source == node_id)
            for node_id in self._node_ids
        }

    @classmethod
    def from_receipt_journal(
        cls,
        graph: Mapping[str, Any],
        journal: ExecutionReceiptJournal,
        *,
        run_id: str,
        estimated_durations: Mapping[str, int] | None = None,
        graph_hash: str = "",
    ) -> GraphObservability:
        """Build a run-scoped view from the durable receipt journal."""
        return cls(
            graph,
            journal.list_run_receipts(run_id),
            run_id=run_id,
            inflight=journal.list_inflight_intents(),
            pool_snapshot=journal.read_pool_snapshot(),
            estimated_durations=estimated_durations,
            graph_hash=graph_hash,
        )

    def _duration_ms(self, node_id: str) -> tuple[int, str]:
        """Return (durationMs, provenance) preferring receipts, then estimates/hints."""
        receipt = self._receipts.get(node_id)
        if receipt is not None and "durationMs" in receipt:
            return _as_int(receipt.get("durationMs"), 0), "receipt"
        if node_id in self._estimated_durations:
            return self._estimated_durations[node_id], "estimate"
        hint = _declared_duration_hint_ms(self._nodes.get(node_id, {}))
        if hint is not None:
            return hint, "duration-hint"
        return 0, "none"

    def _topo_levels(self) -> list[list[str]]:
        incoming = {node_id: len(self._predecessors[node_id]) for node_id in self._node_ids}
        ready = [node_id for node_id in self._node_ids if incoming[node_id] == 0]
        levels: list[list[str]] = []
        seen = 0
        while ready:
            level = list(ready)
            levels.append(level)
            seen += len(level)
            nxt: list[str] = []
            for node_id in level:
                for successor in self._successors[node_id]:
                    incoming[successor] -= 1
                    if incoming[successor] == 0:
                        nxt.append(successor)
            ready = nxt
        if seen != len(self._node_ids):
            raise ObservabilityError("critical path is undefined for a cyclic graph")
        return levels

    def parallel_branch_count(self) -> int:
        """Maximum independent width across topological levels."""
        levels = self._topo_levels()
        return max((len(level) for level in levels), default=0)

    def max_concurrency(self) -> int:
        limits = self._graph.get("spec", {}).get("resourceLimits") or {}
        return max(1, _as_int(limits.get("maxConcurrency"), 1))

    def estimated_model_mix(self) -> dict[str, int]:
        mix: dict[str, int] = {}
        for node_id in self._node_ids:
            receipt = self._receipts.get(node_id)
            if receipt and isinstance(receipt.get("model"), str) and receipt["model"]:
                model = str(receipt["model"])
            else:
                model = _node_model_estimate(self._nodes[node_id])
            mix[model] = mix.get(model, 0) + 1
        return dict(sorted(mix.items()))

    def human_gates(self) -> list[dict[str, Any]]:
        gates: list[dict[str, Any]] = []
        safety = self._graph.get("safety") if isinstance(self._graph.get("safety"), Mapping) else {}
        if safety.get("humanMergeGate") is True:
            gates.append(
                {
                    "kind": "human-merge-gate",
                    "scope": "graph",
                    "nodeId": None,
                }
            )
        for node_id in self._node_ids:
            node = self._nodes[node_id]
            if _is_human_gate_node(node):
                gates.append({"kind": "node-human-gate", "scope": "node", "nodeId": node_id})
        return gates

    def _settled(self, node_id: str) -> bool:
        receipt = self._receipts.get(node_id)
        if not receipt:
            return False
        if receipt.get("state") == "complete":
            return True
        if receipt.get("cacheHit") is True:
            return True
        return receipt.get("verdict") in {"pass", "fail", "skipped"}

    def classify_node(self, node_id: str) -> str:
        """Return the mutually exclusive live state for one node (R11)."""
        if node_id not in self._nodes:
            raise ObservabilityError(f"unknown node {node_id}")
        receipt = self._receipts.get(node_id)
        intent = self._inflight.get(node_id)
        parked = {str(item) for item in self._pool_snapshot.get("parked") or []}
        queued = {str(item) for item in self._pool_snapshot.get("queue") or []}

        if receipt is not None:
            if receipt.get("cacheHit") is True or receipt.get("verdict") == "skipped":
                return "cached/skipped"
            if receipt.get("verdict") == "fail" or (
                receipt.get("state") == "complete" and receipt.get("verdict") != "pass"
            ):
                return "failed"
            if receipt.get("state") == "complete" and receipt.get("verdict") == "pass":
                return "completed"
            if _as_int(receipt.get("attempts"), 1) > 1 and receipt.get("state") != "complete":
                return "retrying"

        coverage: Mapping[str, Any] = {}
        if intent and isinstance(intent.get("coverage"), Mapping):
            coverage = intent["coverage"]
        elif receipt and isinstance(receipt.get("coverage"), Mapping):
            coverage = receipt["coverage"]
        awaiting_human = bool(
            coverage.get("awaitingHumanGate")
            or coverage.get("humanGate")
            or (
                _is_human_gate_node(self._nodes[node_id])
                and not self._settled(node_id)
            )
        )
        if awaiting_human and not self._settled(node_id):
            return "awaiting-human-gate"

        if intent is not None:
            if _as_int(intent.get("attempts"), 1) > 1:
                return "retrying"
            if intent.get("verdict") == "fail":
                return "failed"
            if node_id in parked or node_id in queued:
                return "pool-queued"
            return "running"

        if node_id in parked or node_id in queued:
            return "pool-queued"

        if not self._settled(node_id):
            preds = self._predecessors[node_id]
            if preds and all(self._settled(pred) for pred in preds):
                # Ready but not yet begun — pool-queued when the snapshot lists work.
                return "pool-queued" if (parked or queued or node_id in queued) else "dependency-blocked"
            if preds:
                return "dependency-blocked"
            return "dependency-blocked"

        return "completed"

    def live_status(self) -> dict[str, Any]:
        """Live graph progress with summary counts (R11)."""
        nodes: list[dict[str, Any]] = []
        counts = {state: 0 for state in LIVE_STATES}
        for node_id in self._node_ids:
            state = self.classify_node(node_id)
            counts[state] = counts.get(state, 0) + 1
            entry: dict[str, Any] = {"nodeId": node_id, "state": state}
            if node_id in self._degraded:
                entry["degraded"] = True
                entry["duplicateCount"] = self._degraded[node_id]["duplicateCount"]
            nodes.append(entry)
        failed = [item["nodeId"] for item in nodes if item["state"] == "failed"]
        running = [item["nodeId"] for item in nodes if item["state"] == "running"]
        if failed:
            verdict = "fail"
        elif any(item["state"] not in {"completed", "cached/skipped"} for item in nodes):
            verdict = "partial"
        else:
            verdict = "pass"
        return {
            "runId": self._run_id,
            "graphHash": self._graph_hash or None,
            "queryKey": f"{self._run_id}:{self._graph_hash}" if self._graph_hash else self._run_id,
            "verdict": verdict,
            "nodeCount": len(self._node_ids),
            "counts": {state: counts.get(state, 0) for state in LIVE_STATES},
            "nodes": nodes,
            "failedNodes": failed,
            "runningNodes": running,
            "degradedNodes": sorted(self._degraded),
            "legend": dict(STATE_LEGEND),
        }

    def status(self) -> dict[str, Any]:
        live = self.live_status()
        completed = live["counts"]["completed"] + live["counts"]["cached/skipped"]
        return {
            "runId": self._run_id,
            "verdict": live["verdict"],
            "nodeCount": live["nodeCount"],
            "completedCount": completed,
            "failedNodes": live["failedNodes"],
            "missingNodes": [
                item["nodeId"]
                for item in live["nodes"]
                if item["state"]
                in {
                    "dependency-blocked",
                    "pool-queued",
                    "running",
                    "retrying",
                    "awaiting-human-gate",
                }
            ],
            "counts": live["counts"],
            "degradedNodes": live["degradedNodes"],
        }

    def show(self, node_id: str) -> dict[str, Any]:
        if node_id not in self._nodes:
            raise ObservabilityError(f"unknown node {node_id}")
        receipt = self._receipts.get(node_id)
        intent = self._inflight.get(node_id)
        source = receipt or intent
        if source is None:
            raise ObservabilityError(f"no completed receipt for node {node_id}")
        return {
            "nodeId": node_id,
            "state": self.classify_node(node_id),
            "receipt": dict(source),
            "telemetry": observability_fields(source),
            "degraded": node_id in self._degraded,
        }

    def _blocker_hierarchy(self, node_id: str) -> list[dict[str, Any]]:
        blockers: list[dict[str, Any]] = []
        state = self.classify_node(node_id)
        for pred in self._predecessors[node_id]:
            pred_state = self.classify_node(pred)
            if pred_state == "failed":
                blockers.append(
                    {
                        "kind": "failed-predecessor",
                        "class": "actionable",
                        "nodeId": pred,
                        "detail": f"predecessor {pred} failed",
                    }
                )
            elif pred_state not in {"completed", "cached/skipped"}:
                blockers.append(
                    {
                        "kind": "dependency",
                        "class": "passive-wait",
                        "nodeId": pred,
                        "detail": f"waiting on {pred} ({pred_state})",
                    }
                )
        if state == "pool-queued":
            pools = self._pool_snapshot.get("pools") or {}
            node = self._nodes[node_id]
            pool_name = str((node.get("resources") or {}).get("pool") or "unknown")
            blockers.append(
                {
                    "kind": "pool-capacity",
                    "class": "passive-wait",
                    "pool": pool_name,
                    "detail": f"queued for pool {pool_name}",
                    "poolSnapshot": pools.get(pool_name),
                }
            )
        if state == "awaiting-human-gate":
            blockers.append(
                {
                    "kind": "human-gate",
                    "class": "actionable",
                    "nodeId": node_id,
                    "detail": "awaiting human confirmation or merge gate",
                }
            )
        if state == "failed":
            blockers.append(
                {
                    "kind": "failed-predecessor",
                    "class": "actionable",
                    "nodeId": node_id,
                    "detail": "node itself failed",
                }
            )
        if not blockers and state not in {"completed", "cached/skipped", "running"}:
            blockers.append(
                {
                    "kind": "unknown",
                    "class": "passive-wait",
                    "nodeId": node_id,
                    "detail": f"state={state}",
                }
            )
        blockers.sort(
            key=lambda item: (
                0 if item.get("class") == "actionable" else 1,
                BLOCKER_KIND_ORDER.index(item["kind"])
                if item.get("kind") in BLOCKER_KIND_ORDER
                else len(BLOCKER_KIND_ORDER),
                str(item.get("nodeId") or ""),
            )
        )
        return blockers

    def _next_action(self, node_id: str, state: str) -> dict[str, Any]:
        if state in {"completed", "cached/skipped"}:
            return {
                "action": "none",
                "command": None,
                "detail": "node already settled",
            }
        if state == "failed":
            return {
                "action": "inspect-and-rerun",
                "command": f"/sw-status explain {node_id}",
                "detail": "inspect failure then resume the owning deliver run",
            }
        if state == "awaiting-human-gate":
            return {
                "action": "confirm-human-gate",
                "command": f"/sw-deliver resume-locate --run-id {self._run_id}"
                if self._run_id
                else "/sw-deliver resume-locate",
                "detail": "complete the human gate then resume",
            }
        if state == "pool-queued":
            return {
                "action": "wait-for-pool",
                "command": None,
                "detail": "passive wait until pool capacity frees",
            }
        if state == "dependency-blocked":
            unsettled = [
                pred
                for pred in self._predecessors[node_id]
                if self.classify_node(pred) not in {"completed", "cached/skipped"}
            ]
            return {
                "action": "wait-for-dependencies",
                "command": None,
                "detail": "waiting on: " + (", ".join(unsettled) if unsettled else "predecessors"),
            }
        if state in {"running", "retrying"}:
            return {
                "action": "monitor",
                "command": f"/sw-status explain {node_id}",
                "detail": "node is in flight",
            }
        return {
            "action": "unknown",
            "command": None,
            "detail": f"no canonical action for state {state}",
        }

    def explain(self, node_id: str) -> dict[str, Any]:
        if node_id not in self._nodes:
            return {
                "nodeId": node_id,
                "state": "unknown",
                "verdict": None,
                "predecessors": [],
                "blockers": [
                    {
                        "kind": "unknown",
                        "class": "actionable",
                        "detail": f"unknown node {node_id}",
                    }
                ],
                "nextAction": {
                    "action": "none",
                    "command": None,
                    "detail": "node id is not in the graph",
                },
                "inputHashes": [],
                "outputHashes": [],
                "coverage": {},
                "model": "unknown",
                "attempts": 0,
                "cost": None,
            }
        state = self.classify_node(node_id)
        receipt = self._receipts.get(node_id) or self._inflight.get(node_id) or {}
        telemetry = observability_fields(receipt) if receipt else {
            "tokens": 0,
            "latencyMs": 0,
            "attempts": 0,
            "retries": 0,
            "verificationSurvived": False,
            "costPerAcceptedResult": None,
        }
        payload = {
            "nodeId": node_id,
            "state": state,
            "verdict": receipt.get("verdict"),
            "predecessors": list(self._predecessors[node_id]),
            "blockers": self._blocker_hierarchy(node_id),
            "responsible": {
                "dependencies": list(self._predecessors[node_id]),
                "pool": str((self._nodes[node_id].get("resources") or {}).get("pool") or ""),
            },
            "inputHashes": list(receipt.get("inputHashes") or []),
            "outputHashes": list(receipt.get("outputHashes") or []),
            "coverage": dict(receipt.get("coverage") or {}),
            "model": receipt.get("model", "unknown"),
            "attempts": receipt.get("attempts", 0),
            "cost": telemetry.get("costPerAcceptedResult"),
            "telemetry": telemetry,
            "nextAction": self._next_action(node_id, state),
            "degraded": node_id in self._degraded,
        }
        if node_id in self._degraded:
            payload["degradation"] = dict(self._degraded[node_id])
        return payload

    def critical_path(
        self,
        *,
        estimated_durations: Mapping[str, int] | None = None,
    ) -> dict[str, Any]:
        """Longest path by duration; omit zero-weight paths when no estimates exist (R10)."""
        if estimated_durations:
            for node_id, duration in estimated_durations.items():
                self._estimated_durations[str(node_id)] = max(0, int(duration))

        levels = self._topo_levels()
        order = [node_id for level in levels for node_id in level]

        distances: dict[str, int] = {}
        previous: dict[str, str | None] = {}
        provenance: dict[str, str] = {}
        for node_id in order:
            duration, source = self._duration_ms(node_id)
            provenance[node_id] = source
            predecessors = self._predecessors[node_id]
            parent = max(predecessors, key=lambda item: distances[item], default=None)
            distances[node_id] = duration + (distances[parent] if parent else 0)
            previous[node_id] = parent

        total = max(distances.values(), default=0)
        has_weight = total > 0

        if not has_weight:
            # Zero-weight path: omit rather than report a meaningless chain (R10).
            return {
                "runId": self._run_id,
                "omitted": True,
                "reason": "zero-weight",
                "estimated": False,
                "durationMs": 0,
                "nodes": [],
            }

        end = max(order, key=distances.__getitem__, default=None)
        path: list[str] = []
        while end is not None:
            path.append(end)
            end = previous[end]
        path.reverse()
        estimated = any(provenance[node_id] != "receipt" for node_id in path)
        return {
            "runId": self._run_id,
            "omitted": False,
            "estimated": estimated,
            "provenance": sorted(
                {provenance[node_id] for node_id in path if provenance[node_id] != "none"}
            ),
            "durationMs": distances[path[-1]] if path else 0,
            "nodes": [
                {
                    "nodeId": node_id,
                    "cumulativeDurationMs": distances[node_id],
                    "durationMs": self._duration_ms(node_id)[0],
                    "provenance": provenance[node_id],
                }
                for node_id in path
            ],
        }

    def explain_plan(self) -> dict[str, Any]:
        """Read-only deliver plan summary (R10/R12)."""
        critical = self.critical_path()
        payload: dict[str, Any] = {
            "verdict": "pass",
            "readOnly": True,
            "runId": self._run_id or None,
            "nodeCount": len(self._node_ids),
            "parallelBranches": self.parallel_branch_count(),
            "maxConcurrency": self.max_concurrency(),
            "estimatedModelMix": self.estimated_model_mix(),
            "humanGates": self.human_gates(),
            "criticalPath": critical,
        }
        if critical.get("omitted"):
            payload["criticalPathLabel"] = "omitted-zero-weight"
        elif critical.get("estimated"):
            payload["criticalPathLabel"] = "estimated"
        else:
            payload["criticalPathLabel"] = "measured"
        return payload

    def command(self, name: str, *, node_id: str | None = None) -> dict[str, Any]:
        """Dispatch only the read-only command surface."""
        if name in MUTATING_COMMANDS:
            raise ObservabilityError(
                f"{name} is gated until crash-resume and replay support lands"
            )
        if name not in READ_ONLY_COMMANDS:
            raise ObservabilityError(f"unknown graph observability command: {name}")
        if name == "status":
            return self.status()
        if name == "live":
            return self.live_status()
        if name == "critical-path":
            return self.critical_path()
        if not node_id:
            raise ObservabilityError(f"{name} requires node_id")
        return self.show(node_id) if name == "show" else self.explain(node_id)


def render_graph_text(
    payload: Mapping[str, Any],
    *,
    compact: bool = False,
    mode: str = "progress",
) -> str:
    """Deterministic plain-text rendering for status/explain (no color-only encoding)."""
    lines: list[str] = []
    if mode == "explain":
        node_id = payload.get("nodeId", "?")
        state = payload.get("state", "unknown")
        lines.append(f"node={node_id} state={state}")
        if compact:
            next_action = payload.get("nextAction") or {}
            lines.append(
                f"next={next_action.get('action')} cmd={next_action.get('command')}"
            )
            return "\n".join(lines)
        lines.append(f"verdict={payload.get('verdict')}")
        lines.append(f"model={payload.get('model')} attempts={payload.get('attempts')}")
        lines.append("blockers:")
        for blocker in payload.get("blockers") or []:
            lines.append(
                f"  - [{blocker.get('class')}] {blocker.get('kind')}: {blocker.get('detail')}"
            )
        next_action = payload.get("nextAction") or {}
        lines.append(
            f"next-action: {next_action.get('action')} ({next_action.get('detail')})"
        )
        if next_action.get("command"):
            lines.append(f"resume: {next_action.get('command')}")
        return "\n".join(lines)

    if mode == "plan":
        lines.append(
            f"nodes={payload.get('nodeCount')} parallel={payload.get('parallelBranches')} "
            f"maxConcurrency={payload.get('maxConcurrency')}"
        )
        mix = payload.get("estimatedModelMix") or {}
        mix_text = ",".join(f"{key}:{value}" for key, value in mix.items()) or "none"
        lines.append(f"modelMix={mix_text}")
        gates = payload.get("humanGates") or []
        lines.append(f"humanGates={len(gates)}")
        critical = payload.get("criticalPath") or {}
        label = payload.get("criticalPathLabel", "measured")
        if critical.get("omitted"):
            lines.append("criticalPath=omitted (zero-weight)")
        else:
            nodes = ",".join(
                item.get("nodeId", "") for item in critical.get("nodes") or []
            )
            lines.append(
                f"criticalPath[{label}]={nodes} durationMs={critical.get('durationMs', 0)}"
            )
        return "\n".join(lines)

    # progress
    run_id = payload.get("runId") or "unknown"
    lines.append(f"runId={run_id} verdict={payload.get('verdict')}")
    counts = payload.get("counts") or {}
    if compact:
        summary = " ".join(f"{state}={counts.get(state, 0)}" for state in LIVE_STATES)
        lines.append(summary)
        return "\n".join(lines)
    lines.append("counts:")
    for state in LIVE_STATES:
        lines.append(f"  {state}: {counts.get(state, 0)}")
    lines.append("nodes:")
    for item in payload.get("nodes") or []:
        suffix = " degraded" if item.get("degraded") else ""
        lines.append(f"  {item.get('nodeId')}: {item.get('state')}{suffix}")
    lines.append("legend:")
    legend = payload.get("legend") or STATE_LEGEND
    for state in LIVE_STATES:
        lines.append(f"  {state}: {legend.get(state, '')}")
    return "\n".join(lines)


def run_accessibility(
    *,
    run_id: str | None,
    journal: ExecutionReceiptJournal | None = None,
    graph: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Defined behavior for unknown / inaccessible runs (R11)."""
    if not run_id:
        return {
            "verdict": "unknown",
            "error": "run-id-required",
            "nodes": [],
            "counts": {state: 0 for state in LIVE_STATES},
        }
    if journal is None or graph is None:
        return {
            "verdict": "inaccessible",
            "runId": run_id,
            "error": "graph-or-journal-unavailable",
            "nodes": [],
            "counts": {state: 0 for state in LIVE_STATES},
        }
    try:
        obs = GraphObservability.from_receipt_journal(graph, journal, run_id=run_id)
        return obs.live_status()
    except OSError as exc:
        return {
            "verdict": "inaccessible",
            "runId": run_id,
            "error": f"inaccessible:{exc}",
            "nodes": [],
            "counts": {state: 0 for state in LIVE_STATES},
        }


__all__ = [
    "BLOCKER_KIND_ORDER",
    "CriticalPathNode",
    "GraphObservability",
    "LIVE_STATES",
    "MUTATING_COMMANDS",
    "ObservabilityError",
    "READ_ONLY_COMMANDS",
    "STATE_LEGEND",
    "render_graph_text",
    "run_accessibility",
]
