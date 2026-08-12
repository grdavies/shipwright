#!/usr/bin/env python3
"""Second-order WorkflowGraph capability fixtures."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.convergence_loop import (  # noqa: E402
    ConvergenceBudgets,
    Finding,
    InMemoryFingerprintStore,
    run_convergence_loop,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.kernel_compiler import (  # noqa: E402
    KernelCompilationError,
    compile_workflow_graph,
)
from graph.observability import GraphObservability, ObservabilityError  # noqa: E402
from graph.typed_dataflow import DispatchContext, apply_dispatch_transform  # noqa: E402
from graph.transform_ops import (  # noqa: E402
    TRANSFORM_OPERATOR_NAMES,
    TransformError,
    apply_transform,
)


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()


@pytest.mark.parametrize(
    ("operator", "value", "options", "expected"),
    [
        ("map", [{"v": 2}, {"v": 1}], {"selector": "v"}, [2, 1]),
        ("filter", [{"ok": True}, {"ok": False}], {"selector": "ok"}, [{"ok": True}]),
        ("dedupe", [{"id": 1}, {"id": 1}, {"id": 2}], {"selector": "id"}, [{"id": 1}, {"id": 2}]),
        ("sort", [{"v": "b"}, {"v": "a"}], {"selector": "v"}, [{"v": "a"}, {"v": "b"}]),
        (
            "join",
            {"left": [{"id": 1, "a": "x"}], "right": [{"id": 1, "b": "y"}]},
            {"leftKey": "id", "rightKey": "id"},
            [{"left": {"id": 1, "a": "x"}, "right": {"id": 1, "b": "y"}}],
        ),
        ("reduce", [{"v": 2}, {"v": 3}], {"mode": "sum", "selector": "v"}, 5),
        (
            "quorum",
            ["yes", "no", "yes"],
            {"minimum": 2},
            [{"value": "yes", "count": 2}],
        ),
        ("select", {"nested": {"v": 3}}, {"selector": "/nested/v"}, 3),
        (
            "project",
            {"a": 1, "b": 2},
            {"fields": {"renamed": "b"}},
            {"renamed": 2},
        ),
        (
            "validate-schema",
            {"id": 1},
            {"type": "object", "required": ["id"]},
            {"id": 1},
        ),
        (
            "verify-artifact",
            {"verified": True},
            {"contentHash": _hash({"verified": True})},
            {"verified": True},
        ),
    ],
)
def test_each_transform_operator_is_deterministic_and_replayable(
    operator: str,
    value: Any,
    options: dict[str, Any],
    expected: Any,
) -> None:
    first = apply_transform(operator, value, options)
    replay = apply_transform(operator, value, options)
    assert first == expected
    assert json.dumps(first, sort_keys=True) == json.dumps(replay, sort_keys=True)


def _transform_graph() -> dict[str, Any]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "transform-catalog"},
        "spec": {
            "nodes": [
                {
                    "id": "transform-input",
                    "kind": "transform",
                    "resources": {
                        "pool": "read-only-reviewers",
                        "slots": 1,
                        "timeoutSeconds": 30,
                    },
                    "isolation": {"mode": "process", "writeScope": "read-only"},
                    "verification": {"required": True, "strategy": "mechanical"},
                }
            ],
            "edges": [],
            "resourceLimits": {
                "maxConcurrency": 1,
                "maxDurationSeconds": 60,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def test_transform_catalog_is_registered_in_kernel() -> None:
    compiled = compile_workflow_graph(
        _transform_graph(), transform_operators={"transform-input": "map"}
    )
    assert set(compiled["transformOperatorCatalog"]) == TRANSFORM_OPERATOR_NAMES
    assert compiled["transformOperators"] == {"transform-input": "map"}
    with pytest.raises(KernelCompilationError, match="unknown transform operator"):
        compile_workflow_graph(
            _transform_graph(), transform_operators={"transform-input": "exec"}
        )
    with pytest.raises(TransformError, match="unknown transform operator"):
        apply_transform("exec", [])
    context = DispatchContext(
        node_id="transform-input",
        inputs={"declared": [{"value": 2}]},
        artifact_hashes={"declared": "abc"},
    )
    assert apply_dispatch_transform(
        context, "map", input_edge_id="declared", options={"selector": "value"}
    ) == [2]


def test_convergence_reaches_dry_round_and_persists_only_fingerprints() -> None:
    store = InMemoryFingerprintStore()
    rejected = [
        Finding({"message": "raw finding one"}, tokens=3),
        Finding({"message": "raw finding two"}, tokens=4),
    ]
    result = run_convergence_loop(
        "review",
        lambda _round, _seen: rejected,
        budgets=ConvergenceBudgets(max_rounds=4, max_findings=5, max_tokens=20),
        fingerprint_store=store,
    )
    assert result.converged
    assert [item.new_findings for item in result.rounds] == [2, 0]
    assert result.tokens_used == 14
    persisted = json.dumps(store.values)
    assert "raw finding" not in persisted
    assert all(len(value) == 64 for value in store.values["review"])


def _completed_graph() -> dict[str, Any]:
    graph = _transform_graph()
    graph["metadata"]["name"] = "completed-run"
    graph["spec"]["nodes"] = [
        {**graph["spec"]["nodes"][0], "id": "collect", "kind": "command"},
        {**graph["spec"]["nodes"][0], "id": "verify", "kind": "verifier"},
    ]
    graph["spec"]["edges"] = [{"from": "collect", "to": "verify", "required": True}]
    return graph


def _receipt(node_id: str, duration_ms: int, input_hashes: list[str]) -> dict[str, Any]:
    return {
        "state": "complete",
        "nodeId": node_id,
        "idempotencyKey": f"run:{node_id}",
        "model": "fixture",
        "attempts": 1,
        "tokens": 5,
        "durationMs": duration_ms,
        "inputHashes": input_hashes,
        "outputHashes": [f"{node_id}-hash"],
        "verdict": "pass",
        "coverage": {"verificationSurvived": True},
    }


def test_observability_commands_are_receipts_backed_and_read_only() -> None:
    observability = GraphObservability(
        _completed_graph(),
        [_receipt("collect", 7, []), _receipt("verify", 3, ["collect-hash"])],
        run_id="completed",
    )
    assert observability.command("status")["verdict"] == "pass"
    assert observability.command("show", node_id="collect")["telemetry"]["latencyMs"] == 7
    assert observability.command("explain", node_id="verify")["predecessors"] == [
        "collect"
    ]
    assert observability.command("critical-path") == {
        "runId": "completed",
        "durationMs": 10,
        "nodes": [
            {"nodeId": "collect", "cumulativeDurationMs": 7},
            {"nodeId": "verify", "cumulativeDurationMs": 10},
        ],
    }
    with pytest.raises(ObservabilityError, match="gated"):
        observability.command("replay")


def test_observability_loads_only_requested_run_receipts(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    for run_id, node_id in (
        ("completed", "collect"),
        ("completed", "verify"),
        ("another-run", "collect"),
    ):
        journal.record(
            node_id,
            f"{run_id}:graph:{node_id}",
            {
                "model": "fixture",
                "attempts": 1,
                "tokens": 1,
                "durationMs": 1,
                "inputHashes": [],
                "outputHashes": [f"{node_id}-hash"],
                "verdict": "pass",
                "coverage": {"verificationSurvived": True},
            },
        )
    observability = GraphObservability.from_receipt_journal(
        _completed_graph(), journal, run_id="completed"
    )
    assert observability.status()["verdict"] == "pass"
