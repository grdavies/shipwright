"""PRD 275 R9/R12 — retro painful gap human ack + unattended fail-closed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import planning_gap_capture as pgc


def _write_cfg(repo: Path, cfg: dict) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _retro_payload(*, run_id: str = "retro-2026-08-17") -> dict:
    return {
        "runId": run_id,
        "shippedRef": "abc123",
        "items": [
            {
                "itemId": "retro-item-1",
                "kind": "painful",
                "summary": "Phase verify flaked twice on unrelated paths",
            }
        ],
    }


def test_materialize_requires_persisted_human_ack(tmp_git_repo: Path) -> None:
    _write_cfg(
        tmp_git_repo,
        {"retrospective": {"gapCapture": {"enabled": True, "maxCapturesPerRun": 3}}},
    )
    retro = _retro_payload()
    drafted = pgc.capture_retro_painful(tmp_git_repo, retro)
    assert drafted["verdict"] == "pass"
    signal_id = drafted["drafted"][0]["signalId"]
    digest = drafted["drafted"][0]["digest"]
    with pytest.raises(SystemExit):
        pgc.materialize_retro_gap_draft(tmp_git_repo, signal_id=signal_id, digest=digest)


def test_unattended_dispatch_fail_closed(tmp_git_repo: Path) -> None:
    _write_cfg(
        tmp_git_repo,
        {"retrospective": {"gapCapture": {"enabled": True, "maxCapturesPerRun": 3}}},
    )
    retro = _retro_payload()
    drafted = pgc.capture_retro_painful(tmp_git_repo, retro, unattended=True)
    assert drafted["verdict"] == "pass"
    signal_id = drafted["drafted"][0]["signalId"]
    digest = drafted["drafted"][0]["digest"]
    pgc.confirm_retro_gap_draft(tmp_git_repo, signal_id=signal_id, digest=digest)
    with pytest.raises(SystemExit):
        pgc.materialize_retro_gap_draft(
            tmp_git_repo,
            signal_id=signal_id,
            digest=digest,
            unattended=True,
        )
