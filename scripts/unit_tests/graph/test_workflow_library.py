#!/usr/bin/env python3
"""Saved workflow template library fixtures."""
from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cutover import CutoverStage, DogfoodEvidence  # noqa: E402
from graph.dynamic_proposal import ProposalBudget  # noqa: E402
from graph.workflow_library import (  # noqa: E402
    WorkflowLibraryError,
    approve_template,
    evaluate_saved_template,
    load_template,
    prepare_run,
    save_template,
)


def _graph(step: str = "sw-run --workspace ${workspace}") -> dict[str, Any]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "saved-workflow-fixture"},
        "spec": {
            "nodes": [
                {
                    "id": "run",
                    "kind": "command",
                    "target": {"step": step},
                    "resources": {
                        "pool": "code-writers",
                        "slots": 1,
                        "timeoutSeconds": 30,
                    },
                    "isolation": {
                        "mode": "worktree",
                        "writeScope": "worktree",
                    },
                    "verification": {
                        "required": True,
                        "strategy": "mechanical",
                    },
                }
            ],
            "edges": [],
            "resourceLimits": {
                "maxConcurrency": "${concurrency}",
                "maxDurationSeconds": 120,
            },
            "verification": {"required": True, "failClosed": True},
        },
    }


def _parameters() -> dict[str, dict[str, Any]]:
    return {
        "workspace": {
            "type": "string",
            "required": True,
            "pattern": "^[a-z][a-z0-9-]+$",
        },
        "concurrency": {
            "type": "integer",
            "required": True,
            "minimum": 1,
            "maximum": 4,
        },
    }


def test_save_approve_run_round_trip_is_parameterized_and_reusable(
    tmp_path: Path,
) -> None:
    library = tmp_path / ".sw" / "workflows"
    path = save_template(
        _graph(),
        name="review-workflow",
        root=library,
        parameters=_parameters(),
    )
    saved = path.read_text(encoding="utf-8")

    assert "/Users/" not in saved
    assert "workspace-one" not in saved
    assert "${workspace}" in saved
    with pytest.raises(WorkflowLibraryError, match="requires human approval"):
        prepare_run(
            "review-workflow",
            values={"workspace": "workspace-one", "concurrency": 2},
            root=library,
        )

    approve_template(
        "review-workflow",
        actor="fixture-human",
        approved_at="2026-08-12T00:00:00+00:00",
        root=library,
    )
    first = prepare_run(
        "review-workflow",
        values={"workspace": "workspace-one", "concurrency": 2},
        root=library,
    )
    second = prepare_run(
        "review-workflow",
        values={"workspace": "workspace-two", "concurrency": 3},
        root=library,
    )

    assert first.graph["spec"]["nodes"][0]["target"]["step"].endswith(
        "workspace-one"
    )
    assert first.graph["spec"]["resourceLimits"]["maxConcurrency"] == 2
    assert second.graph["spec"]["nodes"][0]["target"]["step"].endswith(
        "workspace-two"
    )
    assert second.graph["spec"]["resourceLimits"]["maxConcurrency"] == 3
    assert first.compiled["graphHash"] != second.compiled["graphHash"]


@pytest.mark.parametrize(
    "step,error",
    [
        ("sw-run --workspace /Users/example/project", "local path"),
        ("sw-run --token ghp_abcdefghijklmnopqrstuvwxyz", "secret-like"),
        (
            "sw-run --private-key -----BEGIN PRIVATE KEY-----value",
            "secret-like",
        ),
    ],
)
def test_save_rejects_unredacted_paths_and_secrets(
    tmp_path: Path,
    step: str,
    error: str,
) -> None:
    with pytest.raises(WorkflowLibraryError, match=error):
        save_template(
            _graph(step),
            name="unsafe-workflow",
            root=tmp_path / ".sw" / "workflows",
            parameters={},
        )


def test_approval_is_bound_to_exact_template_and_ranges_fail_closed(
    tmp_path: Path,
) -> None:
    library = tmp_path / ".sw" / "workflows"
    save_template(
        _graph(),
        name="bounded-workflow",
        root=library,
        parameters=_parameters(),
    )
    approve_template("bounded-workflow", actor="fixture-human", root=library)

    with pytest.raises(WorkflowLibraryError, match="above its maximum"):
        prepare_run(
            "bounded-workflow",
            values={"workspace": "workspace-one", "concurrency": 5},
            root=library,
        )

    path = library / "bounded-workflow.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["graph"]["spec"]["nodes"][0]["resources"]["timeoutSeconds"] = 31
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(WorkflowLibraryError, match="changed after approval"):
        prepare_run(
            "bounded-workflow",
            values={"workspace": "workspace-one", "concurrency": 2},
            root=library,
        )


def test_approved_template_enters_guarded_dynamic_proposal_boundary(
    tmp_path: Path,
) -> None:
    library = tmp_path / ".sw" / "workflows"
    graph = _graph()
    save_template(
        graph,
        name="guarded-workflow",
        root=library,
        parameters=_parameters(),
    )
    approve_template("guarded-workflow", actor="fixture-human", root=library)
    canonical = deepcopy(graph)
    canonical["spec"]["resourceLimits"]["maxConcurrency"] = 1
    canonical["spec"]["nodes"][0]["target"]["step"] = "sw-canonical"

    decision = evaluate_saved_template(
        "guarded-workflow",
        values={"workspace": "workspace-one", "concurrency": 2},
        canonical_graph=canonical,
        plan_policy="proposed",
        cutover_stage=CutoverStage.FULL,
        cutover_evidence=DogfoodEvidence.passing(completed_runs=3),
        budget=ProposalBudget(
            max_nodes=2,
            max_edges=1,
            max_concurrency=4,
            max_duration_seconds=300,
            max_total_slots=2,
        ),
        root=library,
    )

    assert decision.verdict == "accepted"
    assert decision.used_fallback is False


def test_cli_save_approve_run_round_trip(tmp_path: Path) -> None:
    library = tmp_path / ".sw" / "workflows"
    graph_path = tmp_path / "graph.json"
    parameters_path = tmp_path / "parameters.json"
    graph_path.write_text(json.dumps(_graph()), encoding="utf-8")
    parameters_path.write_text(json.dumps(_parameters()), encoding="utf-8")
    script = _SCRIPTS / "graph" / "workflow_library.py"

    save = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(library),
            "save",
            "--name",
            "cli-workflow",
            "--graph",
            str(graph_path),
            "--parameters",
            str(parameters_path),
        ],
        cwd=_SCRIPTS.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert save.returncode == 0, save.stderr

    blocked = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(library),
            "run",
            "--name",
            "cli-workflow",
            "--set",
            "workspace=workspace-one",
            "--set",
            "concurrency=2",
        ],
        cwd=_SCRIPTS.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert blocked.returncode == 20
    assert "requires human approval" in blocked.stderr

    approve = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(library),
            "approve",
            "--name",
            "cli-workflow",
            "--actor",
            "fixture-human",
        ],
        cwd=_SCRIPTS.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert approve.returncode == 0, approve.stderr

    run = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(library),
            "run",
            "--name",
            "cli-workflow",
            "--set",
            "workspace=workspace-one",
            "--set",
            "concurrency=2",
        ],
        cwd=_SCRIPTS.parent,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    payload = json.loads(run.stdout)
    assert payload["action"] == "prepared"
    assert payload["graph"]["spec"]["resourceLimits"]["maxConcurrency"] == 2
    assert load_template("cli-workflow", root=library)["approval"]["approved"] is True
