"""CI plan generation and named-plan dispatch fixtures (PRD 082 R35)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import ci_plan_gen as cpg
import test_scope as ts


def test_pr_workflow_matches_manifest_and_is_idempotent(repo_root: Path) -> None:
    manifest = repo_root / cpg.MANIFEST_REL
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "pr-test-plan-ci.yml"
        first = cpg.generate_pr_test_plan_workflow(repo_root, manifest_path=manifest, out_path=out)
        second = cpg.generate_pr_test_plan_workflow(repo_root, manifest_path=manifest, out_path=out)
        assert first == second
        assert "do not edit by hand" in first
        assert "pull_request:" in first
        committed = (repo_root / cpg.PR_WORKFLOW_REL).read_text(encoding="utf-8")
        assert committed == first


def test_ci_workflow_contains_named_plan_jobs(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ci.yml"
        text = cpg.generate_ci_workflow(repo_root, out_path=out)
        assert "verify-main-full" in text
        assert "verify-scheduled-full-plus-integration" in text
        assert "minimum-python" in text
        assert "Named plan main-full" in text
        assert "Named plan scheduled-full-plus-integration" in text
        assert "Notify triage owner on nightly failure" in text
        assert "nightly-failure-notify.py" in text
        assert 'if: github.event_name == "push"' not in text
        assert "github.event_name == 'push'" in text


def test_minimum_python_matrix_and_core_suites(repo_root: Path) -> None:
    registry = ts.load_registry(repo_root)
    commands = cpg._minimum_python_plan_commands(registry)
    assert commands
    suite_ids = {suite_id for suite_id, _ in commands}
    core = ts.resolve_named_plan("pull-request-core", [], registry=registry)
    assert suite_ids == set(core["suites"])
    with tempfile.TemporaryDirectory() as tmp:
        text = cpg.generate_ci_workflow(repo_root, out_path=Path(tmp) / "ci.yml")
        assert f'python-version: ["{cpg.MINIMUM_PYTHON}"]' in text
        assert "Vendored pytest bootstrap" in text
        for suite_id, command in commands:
            assert f"minimum-python {suite_id}" in text
            assert command in text


def test_plan_dispatch_selects_expected_suites(repo_root: Path) -> None:
    registry = ts.load_registry(repo_root)
    main_full = ts.resolve_named_plan("main-full", [], registry=registry)
    scheduled = ts.resolve_named_plan("scheduled-full-plus-integration", [], registry=registry)
    minimum = ts.resolve_named_plan("minimum-python", [], registry=registry)
    assert main_full["scope"] == "full"
    assert scheduled["includeIntegration"] is True
    assert minimum["inherits"] == "pull-request-core"
    core = ts.resolve_named_plan("pull-request-core", [], registry=registry)
    assert minimum["suites"] == core["suites"]
    fixture_steps = cpg._ci_yml_fixture_steps(registry)
    assert fixture_steps
    ids = {step_id for step_id, _ in fixture_steps}
    for expected in ("emitter-fixtures", "parity-fixtures", "gate-fixtures"):
        assert expected in ids


def test_ci_workflow_is_idempotent(repo_root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "ci.yml"
        first = cpg.generate_ci_workflow(repo_root, out_path=out)
        second = cpg.generate_ci_workflow(repo_root, out_path=out)
        assert first == second
