#!/usr/bin/env python3
"""Graph status, explain, and estimated critical path (PRD 269 R10/R11/R12)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.observability import (  # noqa: E402
    LIVE_STATES,
    GraphObservability,
    render_graph_text,
)


def _node(node_id: str, **extra: Any) -> dict[str, Any]:
    base = {
        "id": node_id,
        "kind": "command",
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 30,
        },
        "isolation": {"mode": "process", "writeScope": "read-only"},
        "verification": {"required": True, "strategy": "mechanical"},
    }
    base.update(extra)
    return base


def _diamond_graph(**node_extras: Any) -> dict[str, Any]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "status-diamond"},
        "spec": {
            "nodes": [
                _node("build", **node_extras.get("build", {})),
                _node("review-a", kind="verifier", **node_extras.get("review-a", {})),
                _node("review-b", kind="verifier", **node_extras.get("review-b", {})),
                _node("synth", **node_extras.get("synth", {})),
            ],
            "edges": [
                {"from": "build", "to": "review-a", "required": True},
                {"from": "build", "to": "review-b", "required": True},
                {"from": "review-a", "to": "synth", "required": True},
                {"from": "review-b", "to": "synth", "required": True},
            ],
            "resourceLimits": {"maxConcurrency": 2, "maxDurationSeconds": 600},
            "verification": {"required": True, "failClosed": True},
        },
        "safety": {
            "humanMergeGate": True,
            "lockOwner": "fixture",
            "resumeCursor": "fixture",
        },
    }


def _receipt(
    node_id: str,
    *,
    duration_ms: int = 1,
    verdict: str = "pass",
    state: str = "complete",
    cache_hit: bool | None = None,
    attempts: int = 1,
    model: str = "fixture",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "state": state,
        "nodeId": node_id,
        "idempotencyKey": idempotency_key or f"run:graph:{node_id}",
        "model": model,
        "attempts": attempts,
        "tokens": 5,
        "durationMs": duration_ms,
        "inputHashes": [],
        "outputHashes": [f"{node_id}-hash"],
        "verdict": verdict,
        "coverage": {"verificationSurvived": verdict == "pass"},
    }
    if cache_hit is not None:
        payload["cacheHit"] = cache_hit
    return payload


def test_critical_path_uses_estimates_and_omits_zero_weight() -> None:
    graph = _diamond_graph()
    empty = GraphObservability(graph, receipts=[])
    omitted = empty.critical_path()
    assert omitted["omitted"] is True
    assert omitted["nodes"] == []
    assert omitted["reason"] == "zero-weight"

    estimated = GraphObservability(
        graph,
        receipts=[],
        estimated_durations={"build": 10, "review-a": 5, "review-b": 8, "synth": 3},
    )
    path = estimated.critical_path()
    assert path["omitted"] is False
    assert path["estimated"] is True
    assert [item["nodeId"] for item in path["nodes"]] == [
        "build",
        "review-b",
        "synth",
    ]
    assert path["durationMs"] == 21

    measured = GraphObservability(
        graph,
        [
            _receipt("build", duration_ms=7),
            _receipt("review-a", duration_ms=3),
            _receipt("review-b", duration_ms=4),
            _receipt("synth", duration_ms=2),
        ],
        run_id="completed",
    )
    measured_path = measured.critical_path()
    assert measured_path["estimated"] is False
    assert measured_path["durationMs"] == 13
    assert [item["nodeId"] for item in measured_path["nodes"]] == [
        "build",
        "review-b",
        "synth",
    ]


def test_duplicate_receipts_degrade_per_node_not_whole_run() -> None:
    graph = _diamond_graph()
    obs = GraphObservability(
        graph,
        [
            _receipt("build", duration_ms=1, attempts=1, idempotency_key="run:a:build"),
            _receipt("build", duration_ms=9, attempts=2, idempotency_key="run:b:build"),
            _receipt("review-a", duration_ms=1),
            _receipt("review-b", duration_ms=1),
            _receipt("synth", duration_ms=1),
        ],
        run_id="dup",
    )
    status = obs.status()
    assert status["verdict"] == "pass"
    assert status["degradedNodes"] == ["build"]
    live = obs.live_status()
    build = next(item for item in live["nodes"] if item["nodeId"] == "build")
    assert build["degraded"] is True
    assert build["duplicateCount"] == 2


def test_live_states_cover_running_queued_cached_failed() -> None:
    graph = _diamond_graph(
        **{
            "synth": {
                "kind": "human-gate",
            }
        }
    )
    obs = GraphObservability(
        graph,
        [
            _receipt("build", duration_ms=5),
            _receipt("review-a", cache_hit=True, duration_ms=0),
            _receipt("review-b", verdict="fail", duration_ms=2),
        ],
        inflight=[
            {
                "nodeId": "synth",
                "state": "partial",
                "model": "pending",
                "attempts": 1,
                "tokens": 0,
                "durationMs": 0,
                "inputHashes": [],
                "outputHashes": [],
                "verdict": "running",
                "coverage": {"intent": True, "awaitingHumanGate": True},
            }
        ],
        pool_snapshot={"parked": [], "queue": ["review-a"], "pools": {}},
        run_id="live",
    )
    live = obs.live_status()
    by_id = {item["nodeId"]: item["state"] for item in live["nodes"]}
    assert by_id["build"] == "completed"
    assert by_id["review-a"] == "cached/skipped"
    assert by_id["review-b"] == "failed"
    assert by_id["synth"] == "awaiting-human-gate"
    assert set(live["counts"]) == set(LIVE_STATES)

    # pool-queued when ready predecessor settled and node is parked
    queued = GraphObservability(
        _diamond_graph(),
        [_receipt("build", duration_ms=1)],
        pool_snapshot={"parked": ["review-a"], "queue": ["review-b"], "pools": {}},
        run_id="queued",
    )
    states = {item["nodeId"]: item["state"] for item in queued.live_status()["nodes"]}
    assert states["review-a"] == "pool-queued"
    assert states["review-b"] == "pool-queued"
    assert states["synth"] == "dependency-blocked"


def test_explain_blocker_hierarchy_and_next_action() -> None:
    graph = _diamond_graph()
    obs = GraphObservability(
        graph,
        [_receipt("build", duration_ms=1), _receipt("review-a", verdict="fail")],
        run_id="explain",
    )
    explained = obs.explain("synth")
    assert explained["state"] == "dependency-blocked"
    kinds = [item["kind"] for item in explained["blockers"]]
    assert "failed-predecessor" in kinds
    assert explained["blockers"][0]["class"] == "actionable"
    assert explained["nextAction"]["action"] == "wait-for-dependencies"
    assert explained["model"] in {"fixture", "unknown", "build"}

    queued = GraphObservability(
        graph,
        [_receipt("build", duration_ms=1), _receipt("review-a"), _receipt("review-b")],
        pool_snapshot={
            "parked": ["synth"],
            "queue": [],
            "pools": {"code-writers": {"inUse": 1}},
        },
        run_id="explain-queued",
    )
    queued_explain = queued.explain("synth")
    assert queued_explain["state"] == "pool-queued"
    assert any(item["kind"] == "pool-capacity" for item in queued_explain["blockers"])


def test_explain_plan_is_read_only_summary() -> None:
    graph = _diamond_graph()
    obs = GraphObservability(
        graph,
        [],
        estimated_durations={"build": 4, "review-a": 2, "review-b": 2, "synth": 1},
    )
    plan = obs.explain_plan()
    assert plan["readOnly"] is True
    assert plan["nodeCount"] == 4
    assert plan["parallelBranches"] == 2
    assert plan["maxConcurrency"] == 2
    assert plan["criticalPathLabel"] == "estimated"
    assert plan["humanGates"]
    assert plan["estimatedModelMix"]


def test_wave_deliver_explain_plan_cli(tmp_path: Path) -> None:
    graph = _diamond_graph()
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    marker = tmp_path / "state.json"
    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "wave_deliver.py"),
            str(tmp_path),
            "explain-plan",
            "--graph-json",
            str(graph_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["readOnly"] is True
    assert payload["nodeCount"] == 4
    assert payload["parallelBranches"] == 2
    assert not marker.exists()

    # Flag form `/sw-deliver --explain-plan`
    proc2 = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "wave_deliver.py"),
            str(tmp_path),
            "--explain-plan",
            "--graph-json",
            str(graph_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc2.returncode == 0, proc2.stderr
    assert json.loads(proc2.stdout)["readOnly"] is True


def test_status_integrity_graph_progress_and_explain(tmp_path: Path) -> None:
    graph = _diamond_graph()
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(graph), encoding="utf-8")
    journal = ExecutionReceiptJournal.for_run(tmp_path / "sw-graph-runs", "run-1")
    for node_id, duration in (("build", 5), ("review-a", 2)):
        journal.record(
            node_id,
            f"run-1:graph:{node_id}",
            {
                "model": "fixture",
                "attempts": 1,
                "tokens": 1,
                "durationMs": duration,
                "inputHashes": [],
                "outputHashes": [f"{node_id}-hash"],
                "verdict": "pass",
                "coverage": {"verificationSurvived": True},
            },
        )
    journal.write_pool_snapshot({}, parked=["review-b"], queue=[])

    progress = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "status_integrity.py"),
            "graph-progress",
            "--root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--graph-json",
            str(graph_path),
            "--journal-root",
            str(tmp_path / "sw-graph-runs"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert progress.returncode == 0, progress.stderr
    payload = json.loads(progress.stdout)
    by_id = {item["nodeId"]: item["state"] for item in payload["nodes"]}
    assert by_id["build"] == "completed"
    assert by_id["review-b"] == "pool-queued"
    assert "legend" in payload

    explained = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "status_integrity.py"),
            "explain",
            "synth",
            "--root",
            str(tmp_path),
            "--run-id",
            "run-1",
            "--graph-json",
            str(graph_path),
            "--journal-root",
            str(tmp_path / "sw-graph-runs"),
            "--format",
            "text",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert explained.returncode == 0, explained.stderr
    assert "node=synth" in explained.stdout
    assert "blockers:" in explained.stdout

    unknown = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS / "status_integrity.py"),
            "graph-progress",
            "--format",
            "json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert unknown.returncode == 0
    assert json.loads(unknown.stdout)["verdict"] == "unknown"


def test_render_text_is_deterministic_and_has_legend() -> None:
    obs = GraphObservability(_diamond_graph(), [_receipt("build")])
    text = render_graph_text(obs.live_status(), compact=False, mode="progress")
    again = render_graph_text(obs.live_status(), compact=False, mode="progress")
    assert text == again
    assert "legend:" in text
    compact = render_graph_text(obs.live_status(), compact=True, mode="progress")
    assert "completed=" in compact


def test_no_sw_graph_slash_commands_introduced() -> None:
    commands = list((_SCRIPTS.parent / "core" / "commands").glob("sw-graph-*.md"))
    assert commands == []
