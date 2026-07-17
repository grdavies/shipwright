"""WIDEN_GLOBS narrowing — config-only paths must not force full verify (PRD 072 R1)."""

from __future__ import annotations

import pytest

import test_scope as ts


@pytest.fixture
def minimal_registry() -> dict:
    return {
        "version": 1,
        "suites": [
            {
                "id": "doc-fixtures",
                "script": "scripts/test/run_doc_fixtures.py",
                "lanes": ["pr-ci"],
                "classification": "required",
                "ciJobName": "feat-test-plan-doc-fixtures",
                "pathTriggers": ["docs/**"],
                "pytestMarker": "docs",
            },
        ],
    }


@pytest.mark.parametrize(
    "path",
    [
        ".cursor/workflow.config.json",
        "workflow.config.json",
    ],
)
def test_workflow_config_absent_from_widen_globs(path: str) -> None:
    assert path not in ts.WIDEN_GLOBS
    assert ts.widen_reason([path]) is None


def test_config_only_change_does_not_force_full_scope(minimal_registry: dict) -> None:
    plan = ts.build_plan(
        [".cursor/workflow.config.json", "workflow.config.json"],
        registry=minimal_registry,
        scope="phase",
    )
    assert plan["scope"] == "phase"
    assert plan["widenReason"] is None


def test_infra_paths_still_widen(minimal_registry: dict) -> None:
    plan = ts.build_plan(
        ["core/sw-reference/suite-registry.json"],
        registry=minimal_registry,
        scope="phase",
    )
    assert plan["scope"] == "full"
    assert plan["widenReason"] == "global-infra"
