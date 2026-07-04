"""Pytest port of run_test_scope_fixtures scenarios (PRD 054 R10)."""

from __future__ import annotations

import json

import pytest

import test_scope as ts


@pytest.fixture
def sample_registry() -> dict:
    return {
        "version": 1,
        "suites": [
            {
                "id": "doc-fixtures",
                "script": "scripts/test/run_doc_fixtures.py",
                "lanes": ["pr-ci"],
                "classification": "required",
                "ciJobName": "feat-test-plan-doc-fixtures",
                "tags": ["docs"],
                "pathTriggers": ["docs/**", "scripts/test/run_doc_fixtures.py"],
                "pytestMarker": "docs",
            },
            {
                "id": "host-fixtures",
                "script": "scripts/test/run_host_fixtures.py",
                "lanes": ["pr-ci"],
                "classification": "required",
                "ciJobName": "feat-test-plan-host-fixtures",
                "tags": ["host"],
                "pathTriggers": ["scripts/host.py", "scripts/test/run_host_fixtures.py"],
                "pytestMarker": "host",
            },
            {
                "id": "meta-suite",
                "script": "scripts/test/run_suite_registry_fixtures.py",
                "lanes": ["pr-ci"],
                "classification": "required",
                "ciJobName": "feat-test-plan-suite-registry-fixtures",
                "pathTriggers": ["core/sw-reference/suite-registry.json"],
                "pytestPath": "scripts/unit_tests/scope",
            },
        ],
    }


def test_path_to_suite_mapping(sample_registry: dict) -> None:
    plan = ts.build_plan(
        ["docs/guides/testing.md"],
        registry=sample_registry,
        scope="phase",
    )
    assert plan["scope"] == "phase"
    assert "doc-fixtures" in plan["suites"]
    assert "host-fixtures" not in plan["suites"]


def test_widen_list_forces_full(sample_registry: dict) -> None:
    plan = ts.build_plan(
        ["scripts/test_scope.py"],
        registry=sample_registry,
        scope="phase",
    )
    assert plan["scope"] == "full"
    assert plan["widenReason"] == "global-infra"
    assert plan["pytestArgs"] == ["scripts/unit_tests"]


def test_tag_closure_expands_related_suites(sample_registry: dict) -> None:
    reg = json.loads(json.dumps(sample_registry))
    reg["suites"].append(
        {
            "id": "doc-format-fixtures",
            "script": "scripts/test/run_doc_format_fixtures.py",
            "lanes": ["pr-ci"],
            "classification": "required",
            "ciJobName": "feat-test-plan-doc-format-fixtures",
            "tags": ["docs"],
            "pathTriggers": ["scripts/test/run_doc_format_fixtures.py"],
            "pytestMarker": "doc_format",
        }
    )
    plan = ts.build_plan(
        ["scripts/test/run_doc_fixtures.py"],
        registry=reg,
        scope="phase",
        tag_closure=True,
    )
    assert "doc-fixtures" in plan["suites"]
    assert "doc-format-fixtures" in plan["suites"]


def test_tag_closure_disabled(sample_registry: dict) -> None:
    reg = json.loads(json.dumps(sample_registry))
    reg["suites"].append(
        {
            "id": "doc-format-fixtures",
            "script": "scripts/test/run_doc_format_fixtures.py",
            "lanes": ["pr-ci"],
            "classification": "required",
            "ciJobName": "feat-test-plan-doc-format-fixtures",
            "tags": ["docs"],
            "pathTriggers": ["scripts/test/run_doc_format_fixtures.py"],
            "pytestMarker": "doc_format",
        }
    )
    plan = ts.build_plan(
        ["scripts/test/run_doc_fixtures.py"],
        registry=reg,
        scope="phase",
        tag_closure=False,
    )
    assert plan["suites"] == ["doc-fixtures"]


def test_missing_tag_advisory_fallback(sample_registry: dict) -> None:
    plan = ts.build_plan(
        ["scripts/new_pure_logic.py"],
        registry=sample_registry,
        scope="phase",
    )
    assert plan["suites"] == []
    assert any("no-registry-match" in a for a in plan["advisories"])
    assert "scripts/new_pure_logic.py" in plan["paths"]


@pytest.mark.parametrize(
    "scope,expected_marker",
    [
        ("fast", "not integration"),
        ("full", None),
    ],
)
def test_fast_and_full_scope_shapes(
    sample_registry: dict, scope: str, expected_marker: str | None
) -> None:
    plan = ts.build_plan([], registry=sample_registry, scope=scope)
    assert plan["scope"] == scope
    if expected_marker:
        assert expected_marker in plan["pytestArgs"]


def test_path_matches_glob() -> None:
    assert ts.path_matches_glob("docs/guides/testing.md", "docs/**")
    assert not ts.path_matches_glob("scripts/host.py", "docs/**")


def test_full_dist_compare_tier_gate() -> None:
    assert ts.should_run_full_dist_compare("full", []) is True
    assert ts.should_run_full_dist_compare("phase", ["docs/foo.md"]) is False
    assert ts.should_run_full_dist_compare("phase", ["scripts/test_scope.py"]) is True
    assert ts.should_run_full_dist_compare("fast", ["core/sw-reference/suite-registry.json"]) is True
