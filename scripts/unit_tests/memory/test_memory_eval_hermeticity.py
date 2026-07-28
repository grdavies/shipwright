"""Hermeticity fixtures for memory-eval harness (PRD 082 R33, R35)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
MEMORY_EVAL = SCRIPTS / "test" / "memory-eval"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(MEMORY_EVAL) not in sys.path:
    sys.path.insert(0, str(MEMORY_EVAL))

import fixtures as me_fixtures
import harness as me_harness
import metrics as me_metrics
import test_scope as ts


def test_provider_token_in_env_aborts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    env = {"RECALLIUM_API_KEY": "secret-token"}
    with pytest.raises(me_harness.HermeticAbort, match="provider token present"):
        me_harness.assert_hermetic_startup(project, env=env, provider="in-repo")


def test_reachable_network_provider_aborts(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".cursor").mkdir()
    (project / ".cursor" / "workflow.config.json").write_text(
        '{"memory": {"provider": "recallium"}}',
        encoding="utf-8",
    )
    with mock.patch.object(
        me_harness,
        "find_reachable_network_providers",
        return_value=["recallium"],
    ):
        with pytest.raises(me_harness.HermeticAbort, match="network-backed provider reachable"):
            me_harness.assert_hermetic_startup(project, env={}, provider="in-repo")


def test_reserved_prefix_excluded_from_real_reads() -> None:
    ids = [
        me_fixtures.fixture_id("relevant", "a"),
        "real-memory-id",
        me_fixtures.fixture_id("stale", "b"),
    ]
    filtered = me_harness.filter_real_read_results(ids)
    assert filtered == ["real-memory-id"]
    assert all(me_fixtures.is_reserved_id(item) for item in ids if item != "real-memory-id")


def test_smoke_fixture_boots_harness_and_computes_metric_under_changed_domain_selection(
    tmp_path: Path,
) -> None:
    changed = [
        "scripts/test/memory-eval/harness.py",
        "scripts/unit_tests/memory/test_memory_eval_hermeticity.py",
    ]
    pytest_paths = ts.fallback_pytest_paths(changed)
    assert "scripts/unit_tests/memory/test_memory_eval_hermeticity.py" in pytest_paths

    with me_harness.temporary_project(tmp_path) as harness:
        result = me_harness.run_smoke_benchmark(harness, scenario="memory_enabled")

    assert result["scenario"] == "memory_enabled"
    assert "precision_at_k" in result["metrics"]
    assert result["metrics"]["precision_at_k"] >= 0.0
    assert all(
        me_fixtures.is_reserved_id(memory_id)
        for memory_id in result.get("retrievedIds", [])
    )


def test_full_benchmark_emits_all_scenarios(tmp_path: Path) -> None:
    with me_harness.temporary_project(tmp_path) as harness:
        payload = me_harness.run_full_benchmark(harness)

    scenarios = {row["scenario"] for row in payload["scenarios"]}
    assert scenarios == set(me_metrics.SCENARIOS)
    for row in payload["scenarios"]:
        assert set(row["metrics"]) == set(me_metrics.METRIC_NAMES)
