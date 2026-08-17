#!/usr/bin/env python3
"""Learning-store promotion boundary — thin adapt only (PRD 273 R10)."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics import store_adapter  # noqa: E402


PROMOTION_SYMBOLS = frozenset(
    {
        "promotion_eligible",
        "evaluate_promotion",
        "gate_plan_policy_promotion",
        "promote_playbook",
        "recommend_tier_from_cohort",
        "aggregate_cohort_stats",
    }
)


def test_thin_adapter_does_not_reimplement_promotion() -> None:
    source = inspect.getsource(store_adapter)
    for symbol in PROMOTION_SYMBOLS:
        assert symbol not in source
    assert hasattr(store_adapter, "ReviewerMetricsStoreAdapter")
    adapter_methods = {
        name
        for name, value in inspect.getmembers(store_adapter.ReviewerMetricsStoreAdapter)
        if not name.startswith("_") and callable(value)
    }
    assert "promote" not in "".join(adapter_methods).lower()
    assert "playbook" not in source.lower()
