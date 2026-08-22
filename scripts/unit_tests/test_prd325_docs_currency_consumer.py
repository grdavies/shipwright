"""PRD 325 phase 7 — docs-currency consumer soft-skip (R11, R12)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[1]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))


def _load_docs_currency_gate():
    spec = importlib.util.spec_from_file_location(
        "docs_currency_gate",
        scripts / "docs-currency-gate.py",
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _gate_argv(root: Path, state: dict, plan: dict | None = None) -> list[str]:
    state_path = root / "state.json"
    plan_path = root / "plan.json"
    state_path.write_text(json.dumps(state))
    plan_path.write_text(json.dumps(plan or {"prd_number": state.get("prd_number", "325")}))
    return [
        "docs-currency-gate.py",
        str(root),
        str(root),
        str(state_path),
        str(plan_path),
    ]


def test_consumer_skip_payload_shape(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "consumer-fixture"},
        "phases": {"1": {"status": "green-merged"}},
    }

    with patch("sw_scripts_resolve.is_shipwright_self_repo", return_value=False), patch(
        "wave_living_docs.living_doc_write_banned", return_value=True
    ), patch("wave_living_docs.derive_index_status", return_value="in-progress"), patch(
        "wave_living_docs.read_index_status_evidence",
        return_value={"status": "in-progress"},
    ), patch(
        "wave_living_docs.read_completion_evidence", return_value={"prd_id": "325"}
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ):
        rc = dcg.main(_gate_argv(tmp_path, state))

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["verdict"] == "pass"
    skipped = payload["skipped"]
    assert len(skipped) == 4
    assert {row["reason"] for row in skipped} == {"consumer-repo"}
    assert {row["check"] for row in skipped} == set(dcg.INTERNAL_ARTIFACT_CURRENCY_CHECKS)
    assert payload["artifactSet"]


def test_self_repo_runs_artifact_currency_fail_closed(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "shipwright"},
        "phases": {"1": {"status": "green-merged"}},
    }
    index = tmp_path / "docs" / "prds" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text("| # | Unit | Status | PRD status |\n| 325 | x | y | in-progress |\n")

    with patch("sw_scripts_resolve.is_shipwright_self_repo", return_value=True), patch(
        "wave_living_docs.living_doc_write_banned", return_value=False
    ), patch("wave_living_docs.derive_index_status", return_value="in-progress"), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ), patch(
        "docs_currency_081.check_release_guide_artifacts",
        return_value=[{"kind": "guide-stale", "id": "layout"}],
    ):
        with pytest.raises(SystemExit) as exc:
            dcg.main(_gate_argv(tmp_path, state))
    assert exc.value.code == 1


def test_skip_flag_composes_on_self_repo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "shipwright"},
        "phases": {"1": {"status": "pending"}},
    }
    index = tmp_path / "docs" / "prds" / "INDEX.md"
    index.parent.mkdir(parents=True)
    index.write_text("| # | Unit | Status | PRD status |\n| 325 | x | y | in-progress |\n")
    argv = _gate_argv(tmp_path, state) + ["--skip-artifact-currency"]

    with patch("sw_scripts_resolve.is_shipwright_self_repo", return_value=True), patch(
        "wave_living_docs.living_doc_write_banned", return_value=False
    ), patch("wave_living_docs.derive_index_status", return_value="in-progress"), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ), patch(
        "docs_currency_081.check_release_guide_artifacts",
        side_effect=AssertionError("should be skipped"),
    ):
        rc = dcg.main(argv)

    assert rc == 0
    payload = json.loads(capsys.readouterr().out.strip())
    assert payload["verdict"] == "pass"
    assert {row["reason"] for row in payload["skipped"]} == {"skip-artifact-currency"}


def test_consumer_store_evidence_avoids_index_missing_row(tmp_path: Path) -> None:
    dcg = _load_docs_currency_gate()
    state = {
        "prd_number": "325",
        "target": {"slug": "consumer-fixture"},
        "phases": {"1": {"status": "pending"}},
    }

    with patch("sw_scripts_resolve.is_shipwright_self_repo", return_value=False), patch(
        "wave_living_docs.living_doc_write_banned", return_value=False
    ), patch("wave_living_docs.derive_index_status", return_value="not-started"), patch(
        "wave_living_docs.read_index_status_evidence",
        return_value={"status": "not-started"},
    ), patch(
        "planning_migrate_issue_store.gap_backlog_is_readonly", return_value=True
    ):
        rc = dcg.main(_gate_argv(tmp_path, state))

    assert rc == 0
