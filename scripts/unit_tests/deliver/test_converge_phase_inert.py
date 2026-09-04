#!/usr/bin/env python3
"""Converge phase default-off / single-input / closed-kind tests (PRD 342 R42/R43/R55)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import converge_assess as ca
import converge_phase as cp
from graph.ir import validate_workflow_graph
from graph.legacy_adapters import compile_legacy_plan
from graph.node_kinds import (
    CLOSED_NODE_KINDS,
    CONVERGE_ASSESSOR_KIND,
    CONVERGE_FORBIDDEN_RETRY_KIND,
    CONVERGE_PHASE_BODY_KIND,
    converge_compile_kinds,
)


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _baseline_phase_items() -> list[dict]:
    return [
        {
            "id": "1",
            "slug": "alpha",
            "title": "Alpha",
            "branch": "feat/demo-phase-alpha",
            "files": ["scripts/a.py"],
        },
        {
            "id": "2",
            "slug": "beta",
            "title": "Beta",
            "branch": "feat/demo-phase-beta",
            "files": ["scripts/b.py"],
        },
    ]


def _delivery_graph() -> dict:
    plan = {
        "phases": [
            {"id": "1", "slug": "alpha", "name": "Alpha"},
            {"id": "2", "slug": "beta", "name": "Beta"},
        ],
        "maxConcurrency": 1,
        "maxDurationSeconds": 3600,
        "safety": {
            "humanMergeGate": True,
            "lockOwner": "test",
            "resumeCursor": "start",
        },
    }
    return compile_legacy_plan(plan, plan_type="delivery").graph


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    _git_init(root)
    unit = root / "docs" / "prds" / "342-demo"
    unit.mkdir(parents=True)
    _write(
        unit / "342-prd-demo.md",
        "---\nid: 342-prd-demo\ntype: prd\nstatus: draft\ntitle: Demo\n"
        "visibility: public\nbundle: true\n---\n\n# Demo\n\nSee `scripts/demo.py`.\n",
    )
    for name, body in {
        "plan.md": "# Plan\n\nImplement `scripts/demo.py`.\n",
        "data-model.md": "# Data model\n",
        "contracts.md": "# Contracts\n",
        "quickstart.md": "# Quickstart\n",
        "checklist.md": "# Checklist\n",
    }.items():
        _write(unit / name, body)
    _write(root / "scripts" / "demo.py", "print('demo')\n")
    _write(
        unit / "tasks-342-demo.md",
        "---\nid: tasks-342-demo\ntype: tasks\nstatus: draft\ntitle: Tasks\n"
        "visibility: public\nfrozen: true\n---\n\n# Tasks\n\n### 1. Alpha\n\n"
        "- [ ] 1.1 Do thing\n  - **File:** `scripts/demo.py`\n",
    )
    # Prefer the loader's standard config location when present.
    for rel in (
        ".shipwright/workflow.config.json",
        ".cursor/workflow.config.json",
        "workflow.config.json",
    ):
        _write(root / rel, json.dumps({"converge": {"enabled": False}}, indent=2) + "\n")
    return root


def test_converge_disabled_matches_baseline_sequence_and_graph(repo: Path) -> None:
    """R42 — with converge disabled, deliver phase sequence and graph equal baseline."""
    items = _baseline_phase_items()
    baseline_seq = [item["slug"] for item in items]
    task_list = "docs/prds/342-demo/tasks-342-demo.md"
    assert cp.deliver_phase_sequence(repo, items, task_list=task_list, config={}) == baseline_seq
    assert (
        cp.deliver_phase_sequence(
            repo,
            items,
            task_list=task_list,
            config={"converge": {"enabled": False}},
        )
        == baseline_seq
    )

    baseline_graph = _delivery_graph()
    attached = cp.maybe_attach_converge_nodes(
        repo, baseline_graph, config={"converge": {"enabled": False}}
    )
    assert attached == baseline_graph
    assert [node["id"] for node in attached["spec"]["nodes"]] == [
        node["id"] for node in baseline_graph["spec"]["nodes"]
    ]
    assert cp.is_converge_enabled(repo) is False


def test_converge_enabled_still_binds_single_input(repo: Path) -> None:
    """R43 — deliver still binds exactly one required input when converge is on."""
    task_list = "docs/prds/342-demo/tasks-342-demo.md"
    assert cp.deliver_required_inputs(task_list) == [task_list]

    items = _baseline_phase_items()
    extended = cp.maybe_extend_deliver_items(
        repo,
        items,
        task_list=task_list,
        config={"converge": {"enabled": True}},
    )
    assert [item["slug"] for item in extended] == ["alpha", "beta", "converge"]
    assert cp.deliver_required_inputs(task_list) == [task_list]

    result = cp.run_converge_phase(
        repo,
        task_list=task_list,
        skip_verify_execute=True,
        config={"converge": {"enabled": True}},
    )
    assert result["verdict"] == "pass"
    assert result["requiredInputs"] == [task_list]
    assert len(result["requiredInputs"]) == 1


def test_compiled_converge_graph_stays_inside_closed_registry(repo: Path) -> None:
    """R55 — converge compiles as gate+command; no kind outside closed registry."""
    kinds = converge_compile_kinds()
    assert kinds["assessor"] == CONVERGE_ASSESSOR_KIND == "gate"
    assert kinds["phaseBody"] == CONVERGE_PHASE_BODY_KIND == "command"
    assert kinds["forbiddenRetryKind"] == CONVERGE_FORBIDDEN_RETRY_KIND
    assert CONVERGE_FORBIDDEN_RETRY_KIND == "convergence-loop"

    nodes = cp.compile_converge_nodes()
    cp.assert_converge_kinds_closed(nodes)
    used = {node["kind"] for node in nodes}
    assert used == {"gate", "command"}
    assert used <= set(CLOSED_NODE_KINDS)
    assert CONVERGE_FORBIDDEN_RETRY_KIND not in used
    assert cp.converge_node_kinds_used() <= CLOSED_NODE_KINDS

    graph = _delivery_graph()
    attached = cp.maybe_attach_converge_nodes(
        repo, graph, config={"converge": {"enabled": True}}
    )
    validate_workflow_graph(attached)
    all_kinds = {node["kind"] for node in attached["spec"]["nodes"]}
    assert all_kinds <= set(CLOSED_NODE_KINDS)
    assert CONVERGE_FORBIDDEN_RETRY_KIND not in all_kinds
    assert "gate" in all_kinds
    assert any(node["id"] == "converge-assess" for node in attached["spec"]["nodes"])
    assert any(node["id"] == "converge" for node in attached["spec"]["nodes"])

    projected = cp.explain_plan_nodes(attached)
    assert projected
    assert {frozenset(item) for item in projected} == {
        frozenset({"id", "kind", "slug", "title"})
    }
    converge_rows = [
        row for row in projected if row["id"] in {"converge", "converge-assess"}
    ]
    assert len(converge_rows) == 2
    assert {row["kind"] for row in converge_rows} == {"gate", "command"}

    progress = cp.node_progress_from_status_explain(
        {
            "nodes": [
                {"nodeId": "converge-assess", "state": "completed"},
                {"nodeId": "converge", "state": "running"},
            ]
        }
    )
    assert progress == [
        {"nodeId": "converge-assess", "state": "completed"},
        {"nodeId": "converge", "state": "running"},
    ]


def test_assessment_composes_existing_gates_plus_one_bundle_assessor(repo: Path) -> None:
    """R44 — claims audit, gap check, verify gates + exactly one new assessor."""
    report = ca.compose_converge_assessment(
        repo,
        task_list="docs/prds/342-demo/tasks-342-demo.md",
        unit_dir="docs/prds/342-demo",
        skip_verify_execute=True,
    )
    assert report["composedGateIds"] == list(ca.COMPOSED_GATE_IDS)
    assert report["bundleAnchoredAssessorId"] == ca.BUNDLE_ANCHORED_ASSESSOR_ID
    assert report["newAssessorCount"] == 1
    assert report["assessorIds"] == [
        "claims-audit",
        "gap-check",
        "verify-gates",
        "bundle-anchored",
    ]
    assert (
        len([step for step in report["steps"] if step["id"] == "bundle-anchored"]) == 1
    )
