"""PRD 352 R27 — phase-3 installer preservation + event capture smoke."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import installer  # noqa: E402
from wave_journal import (  # noqa: E402
    _emit_milestone,
    emit_discovery,
    ensure_capture_files,
    read_events,
)


def _enable_capture(root: Path) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "capture": {
                    "enabled": True,
                    "gapKeywords": ["undocumented"],
                    "maxSummaryLength": 500,
                    "subAgentSidecarEnabled": True,
                    "maxFileSizeBytes": 52_428_800,
                }
            }
        ),
        encoding="utf-8",
    )


def test_prd352_phase3_installer_preserves_native_skill(tmp_path: Path) -> None:
    install_root = tmp_path / "adapters"
    skill_id = "memory"
    native = install_root / "claude-code" / "skills" / skill_id
    native.mkdir(parents=True)
    body = "# phase3 smoke native body\n"
    (native / "SKILL.md").write_text(body, encoding="utf-8")

    result = installer.install_adapters(
        ["codex"],
        repo=REPO,
        install_root=install_root,
    )
    assert result["verdict"] == "pass"
    assert (native / "SKILL.md").is_file()
    assert (native / "SKILL.md").read_text(encoding="utf-8") == body
    assert any(
        a.get("action") == "preserved_native_body" and a.get("adapter") == "claude-code"
        for a in result.get("duplicate_skill_actions") or []
    )


def test_prd352_phase3_capture_same_second_and_milestone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_capture(tmp_path)
    run_id = "phase3-capture"
    ensure_capture_files(tmp_path, run_id)
    frozen = "2026-09-14T04:00:00Z"
    monkeypatch.setattr("wave_journal._utc_now", lambda: frozen)

    first = emit_discovery(
        "smoke discovery one",
        "phase-3",
        run_id,
        "tool_output",
        "tool-a",
        root=tmp_path,
    )
    second = emit_discovery(
        "smoke discovery two",
        "phase-3",
        run_id,
        "tool_output",
        "tool-b",
        root=tmp_path,
    )
    assert first != second

    mid = _emit_milestone(
        "phase_boundary", "phase-3", run_id, "boundary", root=tmp_path
    )
    assert mid
    # Dedup via dedupSalt — second identical milestone skipped.
    _emit_milestone("phase_boundary", "phase-3", run_id, "boundary again", root=tmp_path)

    discoveries = read_events(run_id, event_types=["discovery"], root=tmp_path)
    milestones = read_events(run_id, event_types=["milestone"], root=tmp_path)
    assert {e["summary"] for e in discoveries} == {
        "smoke discovery one",
        "smoke discovery two",
    }
    assert len(milestones) == 1
    assert milestones[0]["timestamp"] == frozen
    assert milestones[0].get("dedupSalt") == "milestone:phase_boundary"

    errors = (
        tmp_path / ".cursor" / "sw-deliver-runs" / run_id / "capture-errors.jsonl"
    ).read_text(encoding="utf-8")
    assert "duplicate_event_id" in errors
