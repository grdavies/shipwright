"""PRD 275 R23 — per-item digest-bound confirm for retro gap materialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import planning_gap_capture as pgc


def _write_cfg(repo: Path) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"retrospective": {"gapCapture": {"enabled": True, "maxCapturesPerRun": 5}}}),
        encoding="utf-8",
    )


def _retro_batch() -> dict:
    return {
        "runId": "retro-batch-1",
        "items": [
            {"itemId": "a", "kind": "painful", "summary": "first painful"},
            {"itemId": "b", "kind": "painful", "summary": "second painful"},
        ],
    }


def test_per_item_digest_bound_confirm(tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_cfg(tmp_git_repo)
    drafted = pgc.capture_retro_painful(tmp_git_repo, _retro_batch())
    assert len(drafted["drafted"]) == 2
    first = drafted["drafted"][0]
    second = drafted["drafted"][1]
    assert first["digest"] != second["digest"]

    pgc.confirm_retro_gap_draft(
        tmp_git_repo,
        signal_id=first["signalId"],
        digest=first["digest"],
    )
    with pytest.raises(SystemExit):
        pgc.materialize_retro_gap_draft(
            tmp_git_repo,
            signal_id=first["signalId"],
            digest=second["digest"],
        )

    written: dict[str, str] = {}

    def fake_put(r: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        path = r / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written[unit_id] = content

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    out = pgc.materialize_retro_gap_draft(
        tmp_git_repo,
        signal_id=first["signalId"],
        digest=first["digest"],
    )
    assert out["status"] == "materialized"
    assert out["unitId"] in written

    with pytest.raises(SystemExit):
        pgc.confirm_retro_gap_draft(
            tmp_git_repo,
            signal_id=second["signalId"],
            digest="wrong-digest",
        )
