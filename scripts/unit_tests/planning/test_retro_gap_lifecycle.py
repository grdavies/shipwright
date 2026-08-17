"""PRD 275 R11/R18 — retro painful gap lifecycle, route records, idempotency."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import planning_gap_capture as pgc


def _write_cfg(repo: Path, *, enabled: bool = True, cap: int = 3) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "retrospective": {
                    "gapCapture": {"enabled": enabled, "maxCapturesPerRun": cap},
                }
            }
        ),
        encoding="utf-8",
    )


def _retro_payload() -> dict:
    return {
        "runId": "retro-life-1",
        "items": [
            {"itemId": "retro-item-1", "kind": "painful", "summary": "lifecycle painful"},
        ],
    }


def test_retro_emits_painful_to_gap_draft_path(tmp_git_repo: Path) -> None:
    _write_cfg(tmp_git_repo)
    out = pgc.capture_retro_painful(tmp_git_repo, _retro_payload())
    assert out["verdict"] == "pass"
    entry = out["drafted"][0]
    draft_path = tmp_git_repo / entry["path"]
    assert draft_path.is_file()
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    assert draft["kind"] == "painful"
    assert draft["dedupKey"] == "retro:retro-life-1:retro-item-1"
    assert draft["status"] == "draft"


def test_only_kind_painful_auto_drafts(tmp_git_repo: Path) -> None:
    _write_cfg(tmp_git_repo)
    retro = {
        "runId": "retro-mix",
        "items": [
            {"itemId": "w", "kind": "well", "summary": "went fine"},
            {"itemId": "p", "kind": "painful", "summary": "hurt"},
            {"itemId": "c", "kind": "change", "summary": "should change"},
        ],
    }
    out = pgc.capture_retro_painful(tmp_git_repo, retro)
    assert len(out["drafted"]) == 1
    assert out["drafted"][0]["signalId"] == "retro:retro-mix:p"
    assert len(out["skipped"]) == 2


def test_gap_capture_config_enable_and_cap(tmp_git_repo: Path) -> None:
    assert pgc.retro_gap_capture_config(tmp_git_repo)["enabled"] is False
    _write_cfg(tmp_git_repo, enabled=False)
    skipped = pgc.capture_retro_painful(tmp_git_repo, _retro_payload())
    assert skipped["verdict"] == "skipped"

    _write_cfg(tmp_git_repo, enabled=True, cap=1)
    retro = {
        "runId": "cap-run",
        "items": [
            {"itemId": "one", "kind": "painful", "summary": "first"},
            {"itemId": "two", "kind": "painful", "summary": "second"},
        ],
    }
    capped = pgc.capture_retro_painful(tmp_git_repo, retro)
    assert len(capped["drafted"]) == 1
    assert len(capped["overflow"]) == 1
    assert "operatorMessage" in capped


def test_gap_capture_default_disabled_per_run_cap(tmp_git_repo: Path) -> None:
    cfg = pgc.retro_gap_capture_config(tmp_git_repo)
    assert cfg["enabled"] is False
    assert cfg["maxCapturesPerRun"] == pgc.DEFAULT_RETRO_MAX_CAPTURES


def test_route_records_persist_for_audit_resume(tmp_git_repo: Path) -> None:
    _write_cfg(tmp_git_repo)
    drafted = pgc.capture_retro_painful(tmp_git_repo, _retro_payload())
    signal_id = drafted["drafted"][0]["signalId"]
    digest = drafted["drafted"][0]["digest"]
    route_path = pgc.retro_gap_route_path(tmp_git_repo, signal_id)
    assert route_path.is_file()
    history = json.loads(route_path.read_text(encoding="utf-8"))["history"]
    assert history[-1]["action"] == "draft"
    pgc.confirm_retro_gap_draft(tmp_git_repo, signal_id=signal_id, digest=digest)
    history = json.loads(route_path.read_text(encoding="utf-8"))["history"]
    assert [entry["action"] for entry in history] == ["draft", "confirmed"]


def test_painful_lifecycle_idempotent_materialize(
    tmp_git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_cfg(tmp_git_repo)
    drafted = pgc.capture_retro_painful(tmp_git_repo, _retro_payload())
    signal_id = drafted["drafted"][0]["signalId"]
    digest = drafted["drafted"][0]["digest"]
    pgc.confirm_retro_gap_draft(tmp_git_repo, signal_id=signal_id, digest=digest)

    calls: list[str] = []

    def fake_put(r: Path, unit_id: str, body_path_rel: str, content: str) -> None:
        calls.append(unit_id)
        path = r / body_path_rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    monkeypatch.setattr(pgc, "store_put_gap", fake_put)
    first = pgc.materialize_retro_gap_draft(tmp_git_repo, signal_id=signal_id, digest=digest)
    second = pgc.materialize_retro_gap_draft(tmp_git_repo, signal_id=signal_id, digest=digest)
    assert first["unitId"] == second["unitId"]
    assert second.get("idempotent") is True
    assert len(calls) == 1

    repeat = pgc.capture_retro_painful(tmp_git_repo, _retro_payload())
    assert repeat["drafted"][0]["action"] == "reused-draft"
