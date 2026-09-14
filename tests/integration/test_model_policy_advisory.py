"""ModelPolicy advisory enforcement under load — PRD 351 phase 3 (SC-M3, SC-M4, R26)."""
from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from graph.learning_consumers import clear_advisory_snapshot, replace_advisory_snapshot
from graph.reviewer_metrics.selection import UnresolvableIdentity, evaluate_independence
from model_policy_lib import ModelPolicy
from workflow_intelligence import build_advisory


def _load_dispatch():
    here = Path(__file__).resolve()
    candidates = [
        here.parents[2] / "dispatch-check.py",  # scripts/unit_tests/graph
        here.parents[2] / "scripts" / "dispatch-check.py",  # tests/integration
        here.parents[3] / "scripts" / "dispatch-check.py",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    assert path is not None, f"dispatch-check.py not found from {here}"
    spec = importlib.util.spec_from_file_location("dispatch_check_phase3", path)
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


def _fresh_ts(days_ago: float = 0.0) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _qualifying_advisory(**overrides: Any):
    base = dict(
        build_advisory(
            recommended_model="claude-opus-4",
            confidence_score=0.88,
            comparison_basis=["task_type"],
            sample_count=15,
            data_freshness_ts=_fresh_ts(1),
        )
    )
    base.update(overrides)
    return base


def _dimension_variants(i: int) -> dict[str, Any]:
    kind = i % 5
    if kind == 0:
        return {
            "task_type": "implement",
            "effort_hint": "high",
            "complexity_indicators": ["multi-file"],
        }
    if kind == 1:
        return {
            "task_type": "implement",
            "effort_hint": None,
            "complexity_indicators": ["multi-file"],
        }
    if kind == 2:
        return {"task_type": None, "effort_hint": None, "complexity_indicators": None}
    if kind == 3:
        return {
            "task_type": "implement",
            "effort_hint": "low",
            "complexity_indicators": ["single"],
            "legacy": True,
        }
    return {
        "task_type": "review",
        "effort_hint": "medium",
        "complexity_indicators": ["docs"],
    }


def _reviewer_record(i: int) -> dict[str, Any]:
    # All 50 load records resolve; inherit is covered by a dedicated assertion below.
    _ = i
    return {
        "model_id": "claude-opus-4",
        "author_model_identity": ("anthropic", "claude-sonnet-4", "20250514"),
        "reviewer_model_identity": ("anthropic", "claude-opus-4", "20250514"),
    }


@pytest.mark.integration
def test_model_policy_advisory_enforcement_under_load() -> None:
    """SC-M3/SC-M4/R26 — 50 simulated dispatch calls against a fixture advisory store."""
    policy = ModelPolicy.from_tiers(
        {"build": "composer-2.5", "mid": "gpt-5", "deep": "claude-opus-4"}
    )
    min_sample = 10
    max_age = 30

    qualifying = _qualifying_advisory(sample_count=20)
    low_sample = _qualifying_advisory(sample_count=3, recommended_model="gpt-5")
    stale = _qualifying_advisory(
        sample_count=25,
        data_freshness_ts=_fresh_ts(45),
        recommended_model="composer-2.5",
    )

    replace_advisory_snapshot(
        {
            "implement": qualifying,
            "review": low_sample,
            "legacy-task": stale,
        }
    )

    config = {
        "models": {
            "routing": {
                "advisoryRouting": {
                    "enabled": True,
                    "autoApply": False,
                    "minSampleCount": min_sample,
                    "maxFreshnessAgeDays": max_age,
                }
            }
        }
    }

    # Policy-level gates (R26) — independent of dispatch wiring.
    assert policy.evaluate_advisory(
        qualifying, min_sample_count=min_sample, max_freshness_age_days=max_age
    )
    assert not policy.evaluate_advisory(
        low_sample, min_sample_count=min_sample, max_freshness_age_days=max_age
    )
    assert not policy.evaluate_advisory(
        stale, min_sample_count=min_sample, max_freshness_age_days=max_age
    )

    advisory_present = 0
    advisory_expected = 0
    unresolvable = 0

    for i in range(50):
        dims = _dimension_variants(i)
        raw_task = dims.get("task_type")
        task_type = raw_task if raw_task in ("implement", "review") else "implement"

        report = dispatch_check.run_preflight(
            task_type=task_type,
            dimension_record=dims,
            config=config,
            selected_model="composer-2.5",
        )
        lines = report.get("advisory_lines") or []

        # Qualifying recommendation only for implement (review is low-sample).
        if task_type == "implement":
            advisory_expected += 1
            if any(
                str(line).startswith("[advisory] Recommended:") for line in lines
            ):
                advisory_present += 1

        try:
            evaluate_independence(_reviewer_record(i))
        except UnresolvableIdentity:
            unresolvable += 1

    # Inherit still fails closed (SC-M3 signal remains available).
    with pytest.raises(UnresolvableIdentity):
        evaluate_independence({"model_id": "inherit"})

    # SC-M4 — [advisory] present in 100% of preflights with a qualifying recommendation.
    assert advisory_expected > 0
    assert advisory_present == advisory_expected

    # SC-M3 proxy — fewer than 2% UnresolvableIdentity across the 50 calls.
    assert (unresolvable / 50) < 0.02


def test_prd352_r26_advisory_hydrates_in_fresh_subprocess(tmp_path: Path) -> None:
    """PRD 352 R26 — fresh process must hydrate advisory from durable observations.

    In-process replace_advisory_snapshot is insufficient; a new interpreter must
    see get_current_advisory() non-None after durable write. Expected red until R22.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path as P

    store = tmp_path / "observations"
    store.mkdir()
    (store / "advisory.json").write_text(
        json.dumps(
            {
                "recommended_model": "claude-opus-4",
                "confidence_score": 0.9,
                "sample_count": 20,
            }
        ),
        encoding="utf-8",
    )
    repo = P(__file__).resolve().parents[2]
    script = "\n".join(
        [
            "import os, sys",
            f"sys.path.insert(0, {str(repo / 'scripts')!r})",
            f"sys.path.insert(0, {str(repo)!r})",
            "from graph.learning_consumers import get_current_advisory",
            f"os.environ['SW_ADVISORY_STORE'] = {str(store)!r}",
            "adv = get_current_advisory('implement', {})",
            "assert adv is not None, f'expected hydrated advisory, got {adv!r}'",
        ]
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout
