"""PRD 060 R8–R9 verify-override gap capture tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import harness_isolation_lint as hil
import planning_gap_capture as pgc


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def test_verify_override_signature_stable_excludes_reason() -> None:
    override_a = {
        "inconclusiveClass": "no-baseline",
        "reason": "first reason with secret AKIAIOSFODNN7EXAMPLE",
        "when": "2026-01-01T00:00:00Z",
    }
    override_b = {**override_a, "reason": "different reason", "when": "2026-02-02T00:00:00Z"}
    sig_a = pgc.verify_override_signature(override_a, unit_id="060-prd-x", pr_number=42)
    sig_b = pgc.verify_override_signature(override_b, unit_id="060-prd-x", pr_number=42)
    assert sig_a == sig_b


def test_capture_verify_override_create_and_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    _init_repo(root)
    monkeypatch.setenv(hil.LIVE_STORE_OPERATOR_FLAG, "1")
    written: dict[str, str] = {}

    def fake_put(r: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        path = r / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written[unit_id] = content

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    override = {
        "who": "dev@example.com",
        "inconclusiveClass": "no-baseline",
        "reason": "key AKIAIOSFODNN7EXAMPLE leaked",
    }
    first = pgc.capture_verify_override(root, override, unit_id="060-prd-x", pr_number=7)
    assert first["action"] == "created"
    assert first["unitId"]
    body = written[first["unitId"]]
    assert "AKIA" not in body
    assert "redacted" in body.lower() or "[redacted" in body.lower() or "REDACTED" in body

    second = pgc.capture_verify_override(root, override, unit_id="060-prd-x", pr_number=7)
    assert second["action"] == "reused"
    assert second["unitId"] == first["unitId"]


def test_capture_verify_override_skips_missing_required(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    out = pgc.capture_verify_override(
        tmp_path,
        {"inconclusiveClass": "missing-required", "reason": "blocked"},
    )
    assert out["action"] == "skipped"

def test_unisolated_override_add_fails_lint(tmp_path: Path) -> None:
    """R15(j): harness lint flags live override-add without isolation."""
    import harness_isolation_lint as hil

    harness = tmp_path / "scripts/unit_tests/bad_override.py"
    harness.parent.mkdir(parents=True)
    harness.write_text(
        """
bash shipwright-state.py override-add '{"inconclusiveClass":"no-baseline"}'
""",
        encoding="utf-8",
    )
    hit = hil.scan_file(tmp_path, harness)
    assert hit is not None
    assert hit.get("planningStoreWithoutIsolation")


def test_isolated_override_add_passes_lint(tmp_path: Path) -> None:
    """R15(j): isolated override-add with mktemp passes lint."""
    import harness_isolation_lint as hil

    harness = tmp_path / "scripts/unit_tests/ok_override.py"
    harness.parent.mkdir(parents=True)
    harness.write_text(
        """
OV_TMP=$(mktemp -d)
(cd "$OV_TMP/wt" && bash shipwright-state.py override-add '{}')
""",
        encoding="utf-8",
    )
    assert hil.scan_file(tmp_path, harness) is None


def test_harness_improvement_override_block_passes_lint(repo_root: Path) -> None:
    """R15(j): harness_improvement R6 block is isolation-clean after PRD 063 fix."""
    import harness_isolation_lint as hil

    path = repo_root / "scripts/unit_tests/w4/harness_improvement.py"
    assert hil.scan_file(repo_root, path) is None


def test_evidence_matrix_641_642(repo_root: Path) -> None:
    """Evidence matrix maps planning#641/#642 to partition, signal hash, root cause."""
    import verify_evidence_lib as vel

    rows = vel.evidence_matrix_entries()
    assert len(rows) == 1
    row = rows[0]
    assert row["planningIssues"] == ["641", "642"]
    assert row["gapUnits"] == ["gap-263", "gap-264"]
    assert "harness_improvement" in row["partition"]
    assert row["signalHash"] == vel.partition_signal_hash()
    assert "no-baseline" in row["rootCause"]


def test_no_baseline_partition_conclusive(repo_root: Path) -> None:
    """Committed baseline makes the #641/#642 partition conclusive without override."""
    import verify_evidence_lib as vel

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
        restore_committed_baseline=True,
    )
    assert vel.partition_conclusive_without_override(with_baseline)
    assert with_baseline.get("inconclusiveClass") != "no-baseline"


def test_override_runtime_refuse_live_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Harness refuses live issue-store writes unless operator flag is set."""
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
    """Reuse surfaces recurrence without minting a duplicate tracking unit."""
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
    """verify-evidence CLI accepts committed baseline restore for the partition."""
    import verify_evidence_lib as vel

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
            "--restore-committed-baseline",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    verdict = json.loads(proc.stdout)
    assert proc.returncode == vel.VERDICT_EXIT["inconclusive"]
    assert verdict.get("inconclusiveClass") != "no-baseline"
