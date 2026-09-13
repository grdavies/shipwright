"""Unit tests for planning_gap_capture --event-id and gap keyword heuristic (PRD 350 TS3)."""
from __future__ import annotations

import json
from pathlib import Path

import planning_gap_capture as gap
import wave_journal as capture


def _write_config(root: Path, *, enabled: bool = True) -> None:
    cursor = root / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / "workflow.config.json").write_text(
        json.dumps(
            {
                "capture": {
                    "enabled": enabled,
                    "gapKeywords": [
                        "missing documented",
                        "undocumented",
                        "not covered by spec",
                        "gap identified",
                        "sw:gap-marker",
                    ],
                    "maxSummaryLength": 500,
                    "subAgentSidecarEnabled": True,
                    "maxFileSizeBytes": 52_428_800,
                }
            }
        ),
        encoding="utf-8",
    )


def test_parse_flags_event_id() -> None:
    flags = gap.parse_flags(["--signal-id", "s1", "--title", "t", "--event-id", "abc123"])
    assert flags.get("event_id") == "abc123"


def test_capture_gap_embeds_event_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    # Minimal planning dirs stub via monkeypatch if needed — use dry_run path + content builder.
    content_holder: dict[str, str] = {}

    def fake_build(**kwargs):
        fm = kwargs.get("extra_frontmatter") or []
        content_holder["fm"] = "\n".join(fm)
        return "---\nid: gap-1\n---\n# t\n"

    monkeypatch.setattr(gap, "build_enriched_gap_content", fake_build)
    monkeypatch.setattr(gap, "allocate_gap_unit_id", lambda *a, **k: ("gap-1", "gaps/gap-1.md"))
    monkeypatch.setattr(gap, "store_put_gap", lambda *a, **k: None)
    monkeypatch.setattr(gap, "pp", type("P", (), {"load_planning_dirs": staticmethod(lambda root: {})})())

    out = gap.capture_gap(
        tmp_path,
        signal_id="sig-1",
        title="Undocumented helper",
        authoritative=True,
        problem="x",
        context="y",
        event_id="deadbeefdeadbeef",
    )
    assert out.get("unitId") == "gap-1"
    assert "event_id: deadbeefdeadbeef" in content_holder["fm"]


def test_capture_gap_without_event_id_omits_field(tmp_path: Path, monkeypatch) -> None:
    content_holder: dict[str, object] = {}

    def fake_build(**kwargs):
        content_holder["fm"] = kwargs.get("extra_frontmatter")
        return "---\nid: gap-2\n---\n"

    monkeypatch.setattr(gap, "build_enriched_gap_content", fake_build)
    monkeypatch.setattr(gap, "allocate_gap_unit_id", lambda *a, **k: ("gap-2", "gaps/gap-2.md"))
    monkeypatch.setattr(gap, "store_put_gap", lambda *a, **k: None)
    monkeypatch.setattr(gap, "pp", type("P", (), {"load_planning_dirs": staticmethod(lambda root: {})})())

    gap.capture_gap(
        tmp_path,
        signal_id="sig-2",
        title="Normal title",
        authoritative=True,
        problem="x",
        context="y",
    )
    fm = content_holder["fm"]
    assert fm is None or all(not str(x).startswith("event_id:") for x in (fm or []))


def test_keyword_heuristic_positive_and_negative(tmp_path: Path) -> None:
    _write_config(tmp_path, enabled=True)
    assert capture.match_gap_keywords("found undocumented API", capture.gap_keywords(tmp_path))
    assert capture.match_gap_keywords("test coverage gaps", capture.gap_keywords(tmp_path)) is None
