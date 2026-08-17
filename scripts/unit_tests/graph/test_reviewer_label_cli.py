#!/usr/bin/env python3
"""Label ingest CLI tests (PRD 273 R8)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.reviewer_metrics.cohort import CohortIdentity  # noqa: E402
from graph.reviewer_metrics.elo import (  # noqa: E402
    ContestOutcome,
    EloConfig,
    PairwiseContest,
    initial_ratings,
    recompute_from_contests,
)


def _cohort() -> CohortIdentity:
    return CohortIdentity(
        persona_version="persona-v1",
        prompt_version="prompt-v1",
        model_version="model-v1",
        schema_version=1,
        policy_version="policy-v1",
    )


def _run_cli(*args: str, cwd: Path) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(_SCRIPTS / "reviewer-metrics.py"), *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    payload = json.loads(proc.stdout or "{}")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return payload


def test_fixture_labels_to_expected_elo_delta() -> None:
    cohort = _cohort()
    contests = [
        PairwiseContest("reviewer-a", "reviewer-b", ContestOutcome.WIN, cohort),
    ]
    before = initial_ratings(["reviewer-a", "reviewer-b"], cohort, config=EloConfig(k_factor=32.0))
    after = recompute_from_contests(
        contests,
        ["reviewer-a", "reviewer-b"],
        cohort,
        config=EloConfig(k_factor=32.0),
    )
    delta_a = after["reviewer-a"].rating - before["reviewer-a"].rating
    delta_b = after["reviewer-b"].rating - before["reviewer-b"].rating
    assert delta_a > 0
    assert delta_b < 0

    with tempfile.TemporaryDirectory() as tmp:
        fixture = Path(tmp) / "fixture.json"
        fixture.write_text(
            json.dumps(
                {
                    "cohort": cohort.to_dict(),
                    "reviewers": ["reviewer-a", "reviewer-b"],
                    "contests": [
                        {
                            "reviewerA": "reviewer-a",
                            "reviewerB": "reviewer-b",
                            "outcome": "win",
                        }
                    ],
                    "expectedDelta": {
                        "reviewer-a": delta_a,
                        "reviewer-b": delta_b,
                    },
                    "tolerance": 0.01,
                    "kFactor": 32.0,
                }
            ),
            encoding="utf-8",
        )
        out = _run_cli("acceptance", "fixture", "--fixture", str(fixture), cwd=Path(tmp))
        assert out["verdict"] == "pass"


def test_label_ingest_operator_provenance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        out = _run_cli(
            "label",
            "ingest",
            "--finding",
            "finding-cli-1",
            "--run",
            "run-cli-1",
            "--persona",
            "security-reviewer",
            "--model",
            "claude-opus",
            "--surface",
            "sw-review",
            "--window",
            "2026-08-01/2026-08-16",
            "--verdict",
            "tp",
            "--operator",
            "operator-1",
            cwd=repo,
        )
        assert out["verdict"] == "pass"
        assert out["action"] == "label-ingest"
        label = out["label"]
        assert isinstance(label, dict)
        assert label["terminalStatus"] == "confirmed"
        assert label["matchReason"] == "exogenous-human"


def test_label_ingest_fp_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        out = _run_cli(
            "label",
            "ingest",
            "--finding",
            "finding-cli-2",
            "--run",
            "run-cli-2",
            "--persona",
            "style-reviewer",
            "--model",
            "gpt-5",
            "--surface",
            "sw-review",
            "--window",
            "2026-08-01/2026-08-16",
            "--verdict",
            "fp",
            "--operator",
            "operator-2",
            cwd=repo,
        )
        assert out["verdict"] == "pass"
        label = out["label"]
        assert isinstance(label, dict)
        assert label["terminalStatus"] == "rejected"


def test_stabilize_and_ci_stubs_non_gating() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        stabilize = _run_cli("stabilize", "status", cwd=repo)
        ci = _run_cli("ci", "hook", cwd=repo)
        assert stabilize["gating"] is False
        assert ci["gating"] is False
