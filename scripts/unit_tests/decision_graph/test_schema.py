#!/usr/bin/env python3
"""DecisionGraph schema validation unit tests (PRD 280 R1/R7)."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from decision_graph.schema import (  # noqa: E402
    API_VERSION,
    KIND,
    NodeKind,
    ValidationErrorCode,
    minimal_fixture_graph,
    schema_path,
    validate_graph,
)


def test_schema_file_exists_and_matches_api_version() -> None:
    schema = json.loads(schema_path().read_text(encoding="utf-8"))
    assert schema["properties"]["apiVersion"]["const"] == API_VERSION
    assert schema["properties"]["kind"]["const"] == KIND


def test_valid_minimal_graph_passes() -> None:
    result = validate_graph(minimal_fixture_graph())
    assert result["verdict"] == "pass"


def test_all_node_kinds_accepted() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"] = [
        {"id": "d1", "kind": NodeKind.DECISION.value, "status": "open", "question": "Q?"},
        {"id": "r1", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "topic"},
        {
            "id": "h1",
            "kind": NodeKind.HUMAN_ACTION.value,
            "status": "open",
            "title": "Approve deploy",
        },
        {"id": "p1", "kind": NodeKind.PROTOTYPE.value, "status": "open", "title": "Spike"},
        {
            "id": "u1",
            "kind": NodeKind.UNKNOWN.value,
            "status": "resolved",
            "question": "Unknown?",
            "resolution": {"outcome": "deferred"},
        },
    ]
    graph["spec"]["edges"] = []
    result = validate_graph(graph)
    assert result["verdict"] == "pass"


def test_invalid_kind_fails_closed() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"][0]["kind"] = "not-a-kind"
    result = validate_graph(graph)
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result["errors"]}
    assert ValidationErrorCode.SCHEMA_INVALID_KIND.value in codes


def test_missing_decision_question_fails() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"][0].pop("question")
    result = validate_graph(graph)
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result["errors"]}
    assert ValidationErrorCode.SCHEMA_MISSING_FIELD.value in codes


def test_cycle_fixture_fails_with_stable_code() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"] = [
        {"id": "a", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t1"},
        {"id": "b", "kind": NodeKind.RESEARCH.value, "status": "open", "topic": "t2"},
    ]
    graph["spec"]["edges"] = [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]
    result = validate_graph(graph)
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result["errors"]}
    assert ValidationErrorCode.GRAPH_CYCLE.value in codes


def test_dangling_edge_fails_with_stable_code() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["edges"] = [{"from": "d1", "to": "missing"}]
    result = validate_graph(graph)
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result["errors"]}
    assert ValidationErrorCode.GRAPH_DANGLING_EDGE.value in codes


def test_open_unknown_blocks_freeze() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"] = [
        {
            "id": "u1",
            "kind": NodeKind.UNKNOWN.value,
            "status": "open",
            "question": "Unresolved?",
        }
    ]
    graph["spec"]["edges"] = []
    result = validate_graph(graph)
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result["errors"]}
    assert ValidationErrorCode.FREEZE_UNKNOWN_OPEN.value in codes


def test_open_unknown_allowed_when_freeze_check_disabled() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"] = [
        {
            "id": "u1",
            "kind": NodeKind.UNKNOWN.value,
            "status": "open",
            "question": "Unresolved?",
        }
    ]
    graph["spec"]["edges"] = []
    result = validate_graph(graph, check_freeze=False)
    assert result["verdict"] == "pass"


def test_resolved_unknown_requires_resolution() -> None:
    graph = minimal_fixture_graph()
    graph["spec"]["nodes"] = [
        {
            "id": "u1",
            "kind": NodeKind.UNKNOWN.value,
            "status": "resolved",
            "question": "Was unknown",
        }
    ]
    graph["spec"]["edges"] = []
    result = validate_graph(graph)
    assert result["verdict"] == "fail"
    codes = {item["code"] for item in result["errors"]}
    assert ValidationErrorCode.SCHEMA_MISSING_FIELD.value in codes


def test_validate_cli_pass_json() -> None:
    fixture = _SCRIPTS / "test" / "fixtures" / "decision_graph" / "minimal.json"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(json.dumps(minimal_fixture_graph(), indent=2) + "\n", encoding="utf-8")
    from decision_graph.validate import main

    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer), pytest.raises(SystemExit) as exc:
        main(["--graph", str(fixture)])
    assert exc.value.code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["verdict"] == "pass"
