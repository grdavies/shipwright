"""Dispatch advisory preflight integration — PRD 351 phase 2 (TS7, TS8, TS10)."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest

import check_gate_lib as gate
from graph.learning_consumers import clear_advisory_snapshot, replace_advisory_snapshot
from workflow_intelligence import build_advisory


def _load_dispatch():
    path = Path(__file__).resolve().parents[2] / "dispatch-check.py"
    spec = importlib.util.spec_from_file_location("dispatch_check_integration", path)
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


def _qualifying(model: str = "claude-opus-4"):
    return build_advisory(
        recommended_model=model,
        confidence_score=0.91,
        comparison_basis=["task_type", "effort_hint"],
        sample_count=15,
        data_freshness_ts=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )


def test_preflight_advisory_line_format() -> None:
    """TS7 / R16 — properly formatted [advisory] line with required fields."""
    replace_advisory_snapshot({"implement": _qualifying()})
    report = dispatch_check.run_preflight(
        task_type="implement",
        dimension_record={"task_type": "implement"},
        config={
            "models": {
                "routing": {"advisoryRouting": {"enabled": True, "autoApply": False}},
            }
        },
        selected_model="composer-2.5",
    )
    lines = report["advisory_lines"]
    assert len(lines) == 1
    line = lines[0]
    assert line.startswith("[advisory] Recommended: claude-opus-4")
    assert "Confidence: 91%" in line
    assert "Basis: 15 tasks" in line
    assert "Status: read-only" in line
    assert report["selected_model"] == "composer-2.5"
    assert report["advisory_applied"] is False


def test_auto_apply_false_leaves_model_unchanged() -> None:
    """TS8 / R18 — autoApply false → advisory present, model unchanged."""
    replace_advisory_snapshot({"implement": _qualifying("claude-opus-4")})
    report = dispatch_check.run_preflight(
        task_type="implement",
        dimension_record={},
        config={
            "models": {
                "routing": {"advisoryRouting": {"enabled": True, "autoApply": False}},
            }
        },
        selected_model="composer-2.5",
    )
    assert report["selected_model"] == "composer-2.5"
    assert report["advisory_applied"] is False
    assert any(line.startswith("[advisory] Recommended:") for line in report["advisory_lines"])


def test_auto_apply_true_selects_advisory_model() -> None:
    """TS8 — autoApply true with qualifying recommendation selects advisory model."""
    replace_advisory_snapshot({"implement": _qualifying("claude-opus-4")})
    report = dispatch_check.run_preflight(
        task_type="implement",
        dimension_record={},
        config={
            "models": {
                "routing": {
                    "advisoryRouting": {
                        "enabled": True,
                        "autoApply": True,
                        "minSampleCount": 10,
                        "maxFreshnessAgeDays": 30,
                    }
                }
            }
        },
        selected_model="composer-2.5",
    )
    assert report["selected_model"] == "claude-opus-4"
    assert report["advisory_applied"] is True
    assert any("Status: will-apply" in line for line in report["advisory_lines"])


def test_auto_apply_unavailable_model_not_applied() -> None:
    """R19 — autoApply true + excluded model → not applied."""
    replace_advisory_snapshot({"implement": _qualifying("banned-model")})
    report = dispatch_check.run_preflight(
        task_type="implement",
        dimension_record={},
        config={
            "models": {
                "excludedModels": ["banned-model"],
                "routing": {
                    "advisoryRouting": {
                        "enabled": True,
                        "autoApply": True,
                        "minSampleCount": 10,
                    }
                },
            }
        },
        selected_model="composer-2.5",
    )
    assert report["selected_model"] == "composer-2.5"
    assert report["advisory_applied"] is False


def test_unknown_models_routing_key_fails_check_gate() -> None:
    """TS10 / R25 — unknown key under models.routing → errors."""
    cfg = {
        "models": {
            "routing": {
                "commands": {},
                "agents": {},
                "skills": {},
                "advisoryRouting": {"enabled": True},
                "notARealKey": True,
            }
        }
    }
    errors = gate.validate_models_routing(cfg)
    assert errors
    assert any("notARealKey" in err for err in errors)


def test_auto_apply_without_explicit_min_sample_warns() -> None:
    """TS10 / R27 — autoApply true without explicit minSampleCount → warning."""
    cfg = {
        "models": {
            "routing": {
                "advisoryRouting": {"enabled": True, "autoApply": True},
            }
        }
    }
    warnings = gate.validate_models_routing_warnings(cfg)
    assert warnings
    assert any("minSampleCount" in w for w in warnings)


def test_auto_apply_without_enabled_errors() -> None:
    cfg = {
        "models": {
            "routing": {
                "advisoryRouting": {"enabled": False, "autoApply": True, "minSampleCount": 20},
            }
        }
    }
    errors = gate.validate_models_routing(cfg)
    assert any("autoApply" in err for err in errors)
