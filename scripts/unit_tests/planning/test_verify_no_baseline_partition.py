"""PRD 094 R7–R9/R12/R17 verify no-baseline partition + runtime refuse tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import harness_isolation_lint as hil
import planning_gap_capture as pgc
import verify_evidence_lib as vel


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def test_evidence_matrix_641_642(repo_root: Path) -> None:
    """R17 — evidence matrix maps planning#641/#642 to partition, signal hash, root cause."""
    rows = vel.evidence_matrix_entries()
    assert len(rows) == 1
    row = rows[0]
    assert row["planningIssues"] == ["641", "642"]
    assert row["gapUnits"] == ["gap-263", "gap-264"]
    assert "harness_improvement" in row["partition"]
    assert row["signalHash"] == vel.partition_signal_hash()
    assert "no-baseline" in row["rootCause"]


def test_no_baseline_partition_conclusive(repo_root: Path) -> None:
    """R7 — committed baseline makes the #641/#642 partition conclusive without override."""
    fixture_root = repo_root / "scripts" / "test" / "fixtures" / "verify-evidence"
    verify_fail = fixture_root / "verify-fail.json"
    gate_red = fixture_root / "gate-red.json"

    without = vel.compute_verdict(
        verify_path=verify_fail,
        gate_path=gate_red,
        require_gate=True,
        pr_context="off",
    )
    assert without["verdict"] == "inconclusive"
    assert without.get("inconclusiveClass") == "no-baseline"

    with_baseline = vel.compute_verdict(
        verify_path=verify_fail,
        gate_path=gate_red,
        require_gate=True,
        pr_context="off",
        root=repo_root,
    )
    assert vel.partition_conclusive_without_override(with_baseline)
    assert with_baseline.get("inconclusiveClass") != "no-baseline"


def test_override_runtime_refuse_live_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R9 — harness refuses live issue-store writes unless operator flag is set."""
    _init_repo(tmp_path)
    monkeypatch.setenv("SW_HARNESS", "1")
    monkeypatch.delenv(hil.LIVE_STORE_OPERATOR_FLAG, raising=False)

    out = pgc.capture_verify_override(
        tmp_path,
        {"inconclusiveClass": "no-baseline", "reason": "harness probe"},
    )
    assert out["action"] == "refused"
    assert out["error"] == "harness-runtime-refuse-live-planning-store"

    monkeypatch.setenv(hil.LIVE_STORE_OPERATOR_FLAG, "1")
    written: dict[str, str] = {}

    def fake_put(r: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        path = r / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written[unit_id] = content

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    allowed = pgc.capture_verify_override(
        tmp_path,
        {"inconclusiveClass": "no-baseline", "reason": "operator flag"},
    )
    assert allowed["action"] == "created"


def test_no_baseline_no_duplicate_gap_visible_recurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R8 — reuse surfaces recurrence without minting a duplicate gap."""
    _init_repo(tmp_path)
    monkeypatch.setenv(hil.LIVE_STORE_OPERATOR_FLAG, "1")
    written: dict[str, str] = {}

    def fake_put(r: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        path = r / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written[unit_id] = content

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    override = {"inconclusiveClass": "no-baseline", "reason": "first"}
    first = pgc.capture_verify_override(tmp_path, override, unit_id="094-prd-x", pr_number=1)
    second = pgc.capture_verify_override(tmp_path, override, unit_id="094-prd-x", pr_number=1)
    assert first["action"] == "created"
    assert second["action"] == "reused"
    assert second["unitId"] == first["unitId"]
    assert second.get("recurrence", 1) >= 2
    assert len(written) == 1


def test_verify_no_baseline_acceptance(repo_root: Path) -> None:
    """R12 — verify-evidence CLI accepts committed baseline restore for the partition."""
    fixture_root = repo_root / "scripts" / "test" / "fixtures" / "verify-evidence"
    script = repo_root / "scripts" / "verify-evidence.py"
    proc = subprocess.run(
        [
            "python3",
            str(script),
            "--root",
            str(repo_root),
            "--verify-status",
            str(fixture_root / "verify-fail.json"),
            "--gate-json",
            str(fixture_root / "gate-red.json"),
            "--require-gate",
            "--pr-context",
            "off",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    verdict = json.loads(proc.stdout)
    assert proc.returncode == vel.VERDICT_EXIT["inconclusive"]
    assert verdict.get("inconclusiveClass") != "no-baseline"
