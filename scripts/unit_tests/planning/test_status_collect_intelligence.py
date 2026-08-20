#!/usr/bin/env python3
"""Codebase Intelligence status collector unit tests (PRD 280 R14)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from status_collect import (  # noqa: E402
    collect_architecture_radar_last,
    collect_vocabulary_divergence_last,
)


def test_architecture_radar_last_missing(tmp_path: Path) -> None:
    result = collect_architecture_radar_last(tmp_path)
    assert result["verdict"] == "pass"
    assert result["present"] is False
    assert result["readOnly"] is True


def test_architecture_radar_last_present(tmp_path: Path) -> None:
    radar_root = tmp_path / ".cursor" / "sw-architecture-radar"
    scan_dir = radar_root / "scan-1"
    scan_dir.mkdir(parents=True)
    candidates_path = scan_dir / "candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "candidates": [
                    {
                        "modulePath": "scripts/foo",
                        "strength": 80,
                        "disposition": "gap-candidate",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (radar_root / "last.json").write_text(
        json.dumps(
            {
                "scanId": "scan-1",
                "scannedAt": "2026-08-19T12:00:00Z",
                "scanDir": ".cursor/sw-architecture-radar/scan-1",
                "candidatesPath": ".cursor/sw-architecture-radar/scan-1/candidates.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = collect_architecture_radar_last(tmp_path)
    assert result["present"] is True
    assert result["scanId"] == "scan-1"
    assert result["candidateCount"] == 1
    assert result["topCandidates"][0]["modulePath"] == "scripts/foo"


def test_vocabulary_divergence_last_missing(tmp_path: Path) -> None:
    result = collect_vocabulary_divergence_last(tmp_path)
    assert result["verdict"] == "pass"
    assert result["present"] is False


def test_vocabulary_divergence_last_present(tmp_path: Path) -> None:
    artifact_dir = tmp_path / ".cursor" / "sw-vocabulary-divergence"
    artifact_dir.mkdir(parents=True)
    (artifact_dir / "last.json").write_text(
        json.dumps(
            {
                "checkedAt": "2026-08-19T12:00:00Z",
                "maxSeverity": "warn",
                "divergence": [{"concept": "account", "severity": "warn"}],
                "registryTermCount": 2,
                "humanGated": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = collect_vocabulary_divergence_last(tmp_path)
    assert result["present"] is True
    assert result["maxSeverity"] == "warn"
    assert result["divergenceCount"] == 1
