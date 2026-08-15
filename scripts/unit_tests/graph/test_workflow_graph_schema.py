#!/usr/bin/env python3
"""WorkflowGraph IR schema and compilation fixtures."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import capability_docs as cd
import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.ir import (  # noqa: E402
    WorkflowGraphValidationError,
    compile_target,
    load_workflow_graph,
    validate_node_spec,
    validate_workflow_graph,
)


def valid_node(node_id: str = "execute") -> dict[str, object]:
    return {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {
            "pool": "code-writers",
            "slots": 1,
            "timeoutSeconds": 300,
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


def valid_graph() -> dict[str, object]:
    return {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {
            "name": "phase-two",
            "phaseId": "2",
        },
        "spec": {
            "nodes": [
                valid_node("execute"),
                {
                    **valid_node("verify"),
                    "resources": {
                        "pool": "read-only-reviewers",
                        "slots": 1,
                        "timeoutSeconds": 120,
                    },
                    "isolation": {
                        "mode": "process",
                        "writeScope": "read-only",
                    },
                },
            ],
            "edges": [
                {
                    "from": "execute",
                    "to": "verify",
                    "required": True,
                }
            ],
            "resourceLimits": {
                "maxConcurrency": 2,
                "maxDurationSeconds": 600,
            },
            "verification": {
                "required": True,
                "failClosed": True,
            },
        },
    }


def test_schema_files_accept_versioned_workflow_and_node() -> None:
    schema_dir = _SCRIPTS / "graph" / "schema"
    workflow_schema = json.loads(
        (schema_dir / "workflow_graph.schema.json").read_text(encoding="utf-8")
    )
    node_schema = json.loads(
        (schema_dir / "node_spec.schema.json").read_text(encoding="utf-8")
    )
    assert workflow_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert node_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    normalized = validate_node_spec(valid_node())
    assert normalized["execution"]["purity"] == "mutating"
    assert normalized["execution"]["cache"] == "disabled"
    validate_workflow_graph(valid_graph())


@pytest.mark.parametrize(
    "mutator",
    [
        lambda graph: graph.pop("apiVersion"),
        lambda graph: graph.update(apiVersion="shipwright.dev/v0"),
        lambda graph: graph["spec"].update(resourceLimits={"maxConcurrency": 0}),
        lambda graph: graph["spec"]["nodes"][0].update(
            isolation={"mode": "unknown", "writeScope": "scoped"}
        ),
    ],
)
def test_invalid_workflow_graph_fixtures_are_rejected(mutator) -> None:
    graph = valid_graph()
    mutator(graph)
    with pytest.raises(WorkflowGraphValidationError):
        validate_workflow_graph(graph)


def test_load_and_compile_phase_step_plan_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "workflow.json"
    source.write_text(json.dumps(valid_graph()), encoding="utf-8")

    graph = load_workflow_graph(source)
    compiled = compile_target(graph, target="phase-step-plan")

    assert compiled == {
        "version": 1,
        "tier": "phase",
        "phaseType": "ship",
        "phaseId": "2",
        "steps": ["sw-execute", "sw-verify"],
        "sourceApiVersion": "shipwright.dev/v1alpha1",
    }


def test_graph_rejects_duplicate_nodes_and_unknown_edge_endpoints() -> None:
    duplicate = valid_graph()
    duplicate["spec"]["nodes"].append(valid_node("execute"))
    with pytest.raises(WorkflowGraphValidationError, match="duplicate node id"):
        validate_workflow_graph(duplicate)

    dangling = valid_graph()
    dangling["spec"]["edges"][0]["to"] = "missing"
    with pytest.raises(WorkflowGraphValidationError, match="unknown node"):
        validate_workflow_graph(dangling)


@pytest.mark.parametrize(
    "node",
    [
        {"id": "missing-required-fields", "kind": "command"},
        {
            **valid_node(),
            "resources": {
                "pool": "code-writers",
                "slots": 17,
                "timeoutSeconds": 300,
            },
        },
        {
            **valid_node(),
            "verification": {
                "required": True,
                "strategy": "not-a-strategy",
            },
        },
    ],
)
def test_invalid_node_spec_fixtures_are_rejected(node: dict[str, object]) -> None:
    with pytest.raises(WorkflowGraphValidationError):
        validate_node_spec(node)


def test_linear_missing_from_generated_markdown_fails_when_conformance_green(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = cd.load_registry(repo_root)
    rendered = cd.render_root_capabilities_md(repo_root, registry)
    assert "`linear`" in rendered
    stale = rendered.replace("`linear`", "`linear-removed`")
    fixture_dir = tmp_path / "scripts/test/fixtures/planning-provider-conformance"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "linear.ok.json").write_text(
        json.dumps({"verdict": "ok", "provider": "linear", "dimensions": {}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _seed_capability_fixture_tree(repo_root, tmp_path, registry, rendered_root=stale)
    errors = cd.validate_conformance_semantics(tmp_path, registry)
    assert any("linear" in err for err in errors)


def test_red_linear_conformance_fails_even_when_generated_text_matches(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = cd.load_registry(repo_root)
    rendered = cd.render_root_capabilities_md(repo_root, registry)
    assert "`linear` | **shipped**" in rendered
    fixture_dir = tmp_path / "scripts/test/fixtures/planning-provider-conformance"
    fixture_dir.mkdir(parents=True)
    (fixture_dir / "linear.ok.json").write_text(
        json.dumps({"verdict": "fail", "provider": "linear", "dimensions": {}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    _seed_capability_fixture_tree(repo_root, tmp_path, registry, rendered_root=rendered)
    errors = cd.validate_conformance_semantics(tmp_path, registry)
    assert any("linear" in err and "conformance" in err for err in errors)


def _seed_capability_fixture_tree(
    source_root: Path,
    dest_root: Path,
    registry: dict[str, object],
    *,
    rendered_root: str,
) -> None:
    for rel in (
        "core/sw-reference/capability-registry.json",
        "core/sw-reference/kernel-classification.json",
        "core/sw-reference/model-routing.defaults.json",
        "core/providers/issues/CAPABILITIES.md",
        "scripts/graph/schema/workflow_graph.schema.json",
        "scripts/graph/schema/node_spec.schema.json",
    ):
        src = source_root / rel
        dest = dest_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    (dest_root / "CAPABILITIES.md").write_text(rendered_root, encoding="utf-8")
    matrices = cd.collect_family_matrices(dest_root)
    (dest_root / cd.MATRICES_JSON_REL).parent.mkdir(parents=True, exist_ok=True)
    (dest_root / cd.MATRICES_JSON_REL).write_text(
        json.dumps(matrices, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (dest_root / cd.MATRICES_MD_REL).write_text(
        cd.render_family_matrices_md(matrices),
        encoding="utf-8",
    )
    (dest_root / cd.ISSUES_CAPABILITIES_REL).write_text(
        cd.render_issues_capabilities_md(dest_root, registry),
        encoding="utf-8",
    )
