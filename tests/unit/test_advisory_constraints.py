"""Advisory constraints — PRD 351 phase 2 (TS4, TS6, R15–R19, R26)."""
from __future__ import annotations

import importlib.util
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from graph.learning_consumers import (
    clear_advisory_snapshot,
    get_current_advisory,
    replace_advisory_snapshot,
)
from model_policy_lib import ModelPolicy
from workflow_intelligence import AdvisoryRecommendation, build_advisory


def _load_dispatch():
    path = Path(__file__).resolve().parents[2] / "scripts" / "dispatch-check.py"
    spec = importlib.util.spec_from_file_location("dispatch_check_constraints", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


dispatch_check = _load_dispatch()


@pytest.fixture(autouse=True)
def _clear_advisory():
    clear_advisory_snapshot()
    yield
    clear_advisory_snapshot()


def _fresh_advisory(**overrides: Any) -> AdvisoryRecommendation:
    base: dict[str, Any] = dict(
        build_advisory(
            recommended_model="claude-opus-4",
            confidence_score=0.82,
            comparison_basis=["task_type"],
            sample_count=12,
            data_freshness_ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
    )
    base.update(overrides)
    return base  # type: ignore[return-value]


def test_excluded_model_recommendation_suppressed() -> None:
    """TS4 / R17 — excludedModels suppresses surfacing."""
    replace_advisory_snapshot({"implement": _fresh_advisory(recommended_model="banned-model")})
    report = dispatch_check.run_preflight(
        task_type="implement",
        dimension_record={},
        config={
            "models": {
                "excludedModels": ["banned-model"],
                "routing": {"advisoryRouting": {"enabled": True, "autoApply": False}},
            }
        },
        selected_model="composer-2.5",
    )
    assert report["advisory"] is None
    assert any("Insufficient data" in line for line in report["advisory_lines"])
    assert report["selected_model"] == "composer-2.5"


def test_low_sample_fails_policy_evaluate_advisory() -> None:
    """TS4 / R26 — below minSampleCount rejected by ModelPolicy.evaluate_advisory."""
    policy = ModelPolicy.from_tiers(
        {"build": "composer-2.5", "mid": "gpt-5", "deep": "claude-opus-4"}
    )
    advisory: AdvisoryRecommendation = {
        "recommended_model": "claude-opus-4",
        "confidence_score": 0.9,
        "comparison_basis": ["task_type"],
        "sample_count": 3,
        "data_freshness_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    assert policy.evaluate_advisory(advisory, min_sample_count=10) is False


def test_stale_recommendation_suppressed() -> None:
    """TS4 — beyond maxFreshnessAgeDays suppressed."""
    stale_ts = (datetime.now(timezone.utc) - timedelta(days=45)).strftime("%Y-%m-%dT%H:%M:%SZ")
    replace_advisory_snapshot(
        {"implement": _fresh_advisory(data_freshness_ts=stale_ts, sample_count=20)}
    )
    report = dispatch_check.run_preflight(
        task_type="implement",
        dimension_record={},
        config={
            "models": {
                "routing": {
                    "advisoryRouting": {
                        "enabled": True,
                        "autoApply": False,
                        "minSampleCount": 10,
                        "maxFreshnessAgeDays": 30,
                    }
                }
            }
        },
        selected_model="composer-2.5",
    )
    assert report["advisory"] is None
    assert any("Insufficient data" in line for line in report["advisory_lines"])


def test_get_current_advisory_timeout_emits_and_proceeds(monkeypatch, caplog) -> None:
    """TS6 / R15 — lookup timeout → [advisory-timeout] and dispatch proceeds."""

    def _hang(task_type: str, dimension_record: dict) -> AdvisoryRecommendation:
        time.sleep(1.0)
        return _fresh_advisory()

    monkeypatch.setattr(dispatch_check, "get_current_advisory", _hang)
    with caplog.at_level(logging.WARNING):
        report = dispatch_check.run_preflight(
            task_type="implement",
            dimension_record={},
            config={
                "models": {
                    "routing": {
                        "advisoryRouting": {
                            "enabled": True,
                            "lookupTimeoutMs": 20,
                            "autoApply": False,
                        }
                    }
                }
            },
            selected_model="composer-2.5",
        )
    assert "[advisory-timeout]" in report["advisory_lines"]
    assert report["selected_model"] == "composer-2.5"
    assert report["advisory_applied"] is False


def test_get_current_advisory_returns_none_without_snapshot() -> None:
    assert get_current_advisory("implement", {}) is None
