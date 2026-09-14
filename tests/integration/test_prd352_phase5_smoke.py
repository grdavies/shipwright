"""PRD 352 R27 — phase-5 attribution wiring smoke (fresh-process advisory lookup)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_prd352_phase5_fresh_process_advisory_lookup(tmp_path: Path) -> None:
    """AS6 / R22 / R26 / R27 — durable store hydrates advisory in a fresh interpreter."""
    store = tmp_path / "observations"
    store.mkdir()
    (store / "advisory.json").write_text(
        json.dumps(
            {
                "recommended_model": "claude-opus-4",
                "confidence_score": 0.91,
                "sample_count": 24,
                "comparison_basis": ["task_type"],
                "data_freshness_ts": "2026-09-01T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    script = "\n".join(
        [
            "import os, sys",
            f"sys.path.insert(0, {str(REPO / 'scripts')!r})",
            f"sys.path.insert(0, {str(REPO)!r})",
            "from graph.learning_consumers import get_current_advisory, hydrate_advisory_snapshot_from_store",
            f"os.environ['SW_ADVISORY_STORE'] = {str(store)!r}",
            "assert hydrate_advisory_snapshot_from_store('implement') is True",
            "adv = get_current_advisory('implement', {})",
            "assert adv is not None, adv",
            "assert adv['recommended_model'] == 'claude-opus-4'",
            "assert int(adv['sample_count']) >= 10",
        ]
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr + proc.stdout


def test_prd352_phase5_cost_aggregate_confidence_and_failed_attempts() -> None:
    """R24/R25 — cost aggregate emits confidence markers and failed-attempt bucket."""
    sys.path.insert(0, str(REPO / "scripts"))
    from graph.reviewer_metrics.cost import aggregate

    result = aggregate(
        [
            {
                "cost": 10.0,
                "attempt_count": 2,
                "failed_attempt_count": 1,
                "verification_result": "pass",
                "rework_required": False,
            },
            {
                "tokens_input": 4,
                "tokens_output": 6,
                "verification_result": "pass",
                "rework_required": False,
            },
            {
                "verification_result": "unknown",
                "rework_required": False,
            },
        ],
        split_verified=True,
    )
    assert result["cost_per_task_all"] is not None
    assert result["cost_per_task_all_confidence"] in {"measured", "estimated", "unknown"}
    assert result["cost_failed_attempts"] == 5.0
    assert result["cost_failed_attempts_confidence"] == "estimated"
    # Unknown cost must not be coerced into a numeric zero contribution.
    assert result["cost_per_task_all_unknown_count"] == 1
    assert result["cost_per_task_all"] != 0.0 or result["cost_per_task_all_known_count"] == 0
