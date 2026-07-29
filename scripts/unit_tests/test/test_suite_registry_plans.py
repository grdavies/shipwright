"""Named CI plan and changed-domain selection fixtures (PRD 082 R35)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import test_scope as ts


@pytest.fixture
def registry(repo_root: Path) -> dict:
    return ts.load_registry(repo_root)


def test_named_plans_declared_in_registry(registry: dict) -> None:
    plans = ts.registry_plans(registry)
    for plan_id in (
        "pull-request-core",
        "changed-domain",
        "main-full",
        "scheduled-full-plus-integration",
        "minimum-python",
    ):
        assert plan_id in plans, f"missing named plan {plan_id}"


def test_core_domains_always_present(registry: dict) -> None:
    plan = ts.compute_changed_domain_plan(
        ["README.md"],
        registry=registry,
    )
    for domain_id in ts.CORE_DOMAIN_IDS:
        assert domain_id in plan["alwaysIncludeDomains"]
        assert domain_id in plan["domains"]
    for suite_id in (
        "planning-store-fixtures",
        "planning-unit-fixtures",
        "memory-provider-fixtures",
        "memory-sot-fixtures",
        "memory-prework-fixtures",
        "guardrail-rules-resolution-fixtures",
        "guardrail-matrix-fixtures",
    ):
        assert suite_id in plan["suites"]


def test_docs_change_selects_docs_domain_suites(registry: dict) -> None:
    plan = ts.compute_changed_domain_plan(
        ["docs/guides/workflows.md"],
        registry=registry,
    )
    assert "docs" in plan["matchedDomains"]
    assert "doc-fixtures" in plan["suites"]
    assert "planning-store-fixtures" in plan["suites"]


def test_deliver_change_selects_deliver_domain_suites(registry: dict) -> None:
    plan = ts.compute_changed_domain_plan(
        ["scripts/ship_loop.py"],
        registry=registry,
    )
    assert "deliver" in plan["matchedDomains"]
    assert "deliver-concurrency-fixtures" in plan["suites"]


def test_redaction_path_includes_eval_suite(registry: dict) -> None:
    plan = ts.compute_changed_domain_plan(
        ["scripts/memory_redact.py"],
        registry=registry,
    )
    assert plan["evalIncluded"] is True
    assert "memory-eval-fixtures" in plan["suites"]


def test_provider_path_includes_eval_suite(registry: dict) -> None:
    plan = ts.compute_changed_domain_plan(
        ["providers/recallium-rules.py"],
        registry=registry,
    )
    assert plan["evalIncluded"] is True
    assert "memory-eval-fixtures" in plan["suites"]


def test_minimum_python_inherits_pull_request_core(registry: dict) -> None:
    core = ts.resolve_named_plan("pull-request-core", [], registry=registry)
    minimum = ts.resolve_named_plan("minimum-python", [], registry=registry)
    assert minimum["inherits"] == "pull-request-core"
    assert minimum["suites"] == core["suites"]


def test_main_full_plan_uses_full_scope(registry: dict) -> None:
    plan = ts.resolve_named_plan("main-full", [], registry=registry)
    assert plan["scope"] == "full"
    assert plan["pytestArgs"] == ["scripts/unit_tests"]


def test_scheduled_plan_requests_integration(registry: dict) -> None:
    plan = ts.resolve_named_plan("scheduled-full-plus-integration", [], registry=registry)
    assert plan["scope"] == "full"
    assert plan["includeIntegration"] is True


def test_registry_json_is_valid(registry: dict) -> None:
    assert isinstance(registry.get("suites"), list)
    assert isinstance(registry.get("plans"), dict)
    assert isinstance(registry.get("domains"), dict)
    json.dumps(registry)
