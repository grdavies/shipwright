"""PRD 062 phase 2 — terminal docs-currency and prepare degrade (R15 d–e)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from wave_terminal import is_recoverable_planning_failure


@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "degraded", "notice": "issue-store-unreachable:timeout"},
        {"verdict": "fail", "notice": "prd-unit-not-found:062"},
        {"verdict": "pass", "append": {"verdict": "degraded", "notice": "planning-store-put-failed"}},
    ],
)
def test_recoverable_planning_failure_markers(payload: dict) -> None:
    """R15(e) — recoverable planning_store failures are classified for prepare degrade."""
    assert is_recoverable_planning_failure(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"verdict": "fail", "error": "living-doc currency drift"},
        {"verdict": "fail", "drift": [{"kind": "index-status"}]},
        {"error": "task-list currency divergence"},
    ],
)
def test_fatal_failures_are_not_recoverable(payload: dict) -> None:
    """R15(e) — fatal drift / currency failures remain fail-closed."""
    assert not is_recoverable_planning_failure(payload)


def test_docs_currency_gate_passes_slug_to_index_evidence(tmp_path: Path) -> None:
    """R15(d) — docs-currency uses deliver target slug for issue-store index lookup."""
    import importlib.util

def _load_docs_currency_gate():
    spec = importlib.util.spec_from_file_location(
        "docs_currency_gate",
        scripts / "docs-currency-gate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


    root = tmp_path
    state_path = root / "state.json"
    plan_path = root / "plan.json"
    state = {
        "prd_number": "062",
        "target": {"slug": "deliver-issue-store-hardening-and-loop-perf"},
        "phases": {"1": {"status": "green-merged"}},
    }
    state_path.write_text(json.dumps(state))
    plan_path.write_text(json.dumps({"prd_number": "062"}))

    calls: list[str | None] = []

    def _fake_evidence(_root, prd, *, slug=None):
        calls.append(slug)
        return {"status": "in-progress"}

    with patch("wave_living_docs.living_doc_write_banned", return_value=True), patch(
        "wave_living_docs.derive_index_status", return_value="in-progress"
    ), patch("wave_living_docs.read_index_status_evidence", side_effect=_fake_evidence), patch(
        "wave_living_docs.read_completion_evidence", return_value={"prd_id": "062"}
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ):
        argv = [
            "docs-currency-gate.py",
            str(root),
            str(root),
            str(state_path),
            str(plan_path),
        ]
        rc = dcg.main(argv)
    assert rc == 0
    assert calls == ["deliver-issue-store-hardening-and-loop-perf"]


def test_docs_currency_skips_gap_backlog_integrity_when_readonly(tmp_path: Path) -> None:
    """R15(d) — readonly gap-backlog shim skips integrity subprocess."""
    import importlib.util

def _load_docs_currency_gate():
    spec = importlib.util.spec_from_file_location(
        "docs_currency_gate",
        scripts / "docs-currency-gate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


    root = tmp_path
    state_path = root / "state.json"
    plan_path = root / "plan.json"
    state = {
        "prd_number": "062",
        "target": {"slug": "fixture"},
        "phases": {"1": {"status": "green-merged"}},
    }
    state_path.write_text(json.dumps(state))
    plan_path.write_text(json.dumps({}))

    with patch("wave_living_docs.living_doc_write_banned", return_value=False), patch(
        "wave_living_docs.derive_index_status", return_value="in-progress"
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ), patch(
        "subprocess.run", side_effect=AssertionError("gap_backlog check should be skipped")
    ):
        # Provide INDEX row so gate passes without store evidence
        index = root / "docs" / "prds" / "INDEX.md"
        index.parent.mkdir(parents=True)
        index.write_text("| # | Unit | Status | PRD status |\n| 062 | x | y | in-progress |\n")
        argv = [
            "docs-currency-gate.py",
            str(root),
            str(root),
            str(state_path),
            str(plan_path),
        ]
        rc = dcg.main(argv)
    assert rc == 0
