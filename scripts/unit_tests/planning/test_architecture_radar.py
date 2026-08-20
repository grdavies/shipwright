"""Unit tests for architecture radar (PRD 280 R3/R4/R6/R17)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import architecture_radar as radar


def _write_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return signals


def test_active_module_outranks_cold_module() -> None:
    signals = _write_signals(
        [
            {
                "signal": "git-churn",
                "windowDays": 30,
                "byPath": {"cold/pkg/mod.py": 2, "active/pkg/mod.py": 12},
            },
            {
                "signal": "import-fanout",
                "byPath": {"cold/pkg/mod.py": 15, "active/pkg/mod.py": 3},
            },
            {
                "signal": "activity-bias",
                "minPrCount": 3,
                "lastPrs": 30,
                "byPath": {"active/pkg/mod.py": 5},
            },
        ]
    )
    scored = radar.score_candidates(Path("/tmp/unused"), signals=signals)
    candidates = scored["candidates"]
    assert len(candidates) >= 2
    active = next(item for item in candidates if item["modulePath"] == "active/pkg")
    cold = next(item for item in candidates if item["modulePath"] == "cold/pkg")
    assert active["strength"] > cold["strength"]
    assert active["activityBiasApplied"] is True
    assert cold["activityBiasApplied"] is False


def test_candidate_schema_fields_present() -> None:
    signals = _write_signals(
        [
            {"signal": "git-churn", "windowDays": 30, "byPath": {"scripts/foo.py": 3}},
            {"signal": "activity-bias", "byPath": {}},
        ]
    )
    scored = radar.score_candidates(Path("/tmp/unused"), signals=signals)
    candidate = scored["candidates"][0]
    assert candidate["modulePath"] == "scripts"
    assert isinstance(candidate["strength"], int)
    assert 0 <= candidate["strength"] <= 100
    assert isinstance(candidate["evidence"], list)
    assert candidate["evidence"][0]["signal"]
    assert "value" in candidate["evidence"][0]
    assert candidate["improvement"]
    assert candidate["localityEffect"]
    assert candidate["disposition"] in radar.DISPOSITIONS


def test_emit_without_confirm_skips_gap_capture(tmp_path: Path) -> None:
    root = tmp_path
    (root / ".cursor").mkdir(parents=True)
    candidates = [
        {
            "modulePath": "scripts/hot",
            "strength": 85,
            "evidence": [{"signal": "reverts", "value": 2, "window": 30, "source": "test"}],
            "improvement": "stabilize",
            "localityEffect": "local",
            "disposition": "gap-candidate",
        }
    ]
    scan_id = "test-scan"
    scan_dir = root / radar.RADAR_ARTIFACT_ROOT / scan_id
    scan_dir.mkdir(parents=True)
    (scan_dir / "candidates.json").write_text(
        json.dumps({"scanId": scan_id, "candidates": candidates}, indent=2),
        encoding="utf-8",
    )
    (root / radar.RADAR_ARTIFACT_ROOT / "last.json").write_text(
        json.dumps(
            {
                "scanId": scan_id,
                "candidatesPath": f"{radar.RADAR_ARTIFACT_ROOT}/{scan_id}/candidates.json",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    mock_put = MagicMock()
    out = radar.emit_gap_drafts(root, candidates, confirm=False, put_gap_draft_fn=mock_put)
    assert out["gapCaptureInvoked"] is False
    assert out["skipped"]["confirmRequired"] == 1
    mock_put.assert_not_called()


def test_emit_with_confirm_invokes_gap_capture(tmp_path: Path) -> None:
    root = tmp_path
    candidates = [
        {
            "modulePath": "scripts/hot",
            "strength": 85,
            "evidence": [],
            "improvement": "stabilize",
            "localityEffect": "local",
            "disposition": "gap-candidate",
        }
    ]
    mock_put = MagicMock(return_value={"signalId": "radar-abc", "status": "draft"})
    out = radar.emit_gap_drafts(root, candidates, confirm=True, put_gap_draft_fn=mock_put)
    assert out["gapCaptureInvoked"] is True
    assert len(out["emitted"]) == 1
    mock_put.assert_called_once()


def test_scan_writes_artifacts_without_git_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "radar@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Radar"], cwd=root, check=True)
    (root / "scripts").mkdir()
    (root / "scripts" / "a.py").write_text("print('a')\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
    before_diff = subprocess.check_output(["git", "diff", "--name-only"], cwd=root, text=True)

    def fake_collect_all(_root: Path) -> dict[str, Any]:
        return {
            "signals": [
                {"signal": "git-churn", "windowDays": 30, "byPath": {"scripts/a.py": 1}},
                {"signal": "activity-bias", "byPath": {}},
            ]
        }

    monkeypatch.setattr(radar.cis, "collect_all", fake_collect_all)
    out = radar.cmd_scan(root)
    after_diff = subprocess.check_output(["git", "diff", "--name-only"], cwd=root, text=True)
    assert before_diff == after_diff
    assert out["verdict"] == "pass"
    assert (root / out["candidatesPath"]).is_file()
