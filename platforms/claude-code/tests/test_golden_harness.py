"""Native-schema golden scenarios for Claude Code adapter (PRD 349 R1–R6)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
GEN = REPO / "platforms" / "claude-code" / "generators"
ADAPTERS = REPO / "platforms" / "claude-code" / "adapters"
for path in (GEN, ADAPTERS, REPO / "core", REPO / "core" / "hooks", REPO / "scripts", REPO / "sw"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from event_registry import registered_host_events, unsupported_events  # noqa: E402
from hook_manifest import (  # noqa: E402
    build_hooks_manifest,
    is_legacy_event_command_form,
    validate_native_hooks_manifest,
)
from tool_name_map import map_tool_name  # noqa: E402

sys.path.insert(0, str(REPO / "core"))
from adapters.pre_tool_evaluator import evaluate_pre_tool  # noqa: E402


def test_r1_native_hooks_manifest_matcher_groups() -> None:
    events = registered_host_events("claude-code")
    manifest = build_hooks_manifest(events=events, command='python3 "hook.py"')
    errors = validate_native_hooks_manifest(manifest)
    assert errors == []
    assert not is_legacy_event_command_form(manifest)
    for event, groups in manifest["hooks"].items():
        assert isinstance(groups, list)
        assert "matcher" in groups[0]
        assert groups[0]["hooks"][0]["type"] == "command"


def test_r2_context_switch_unsupported_not_registered() -> None:
    events = registered_host_events("claude-code")
    assert "ContextSwitch" not in events
    unsupported = unsupported_events("claude-code")
    assert any(
        row.get("canonical") == "ContextSwitch" and row.get("unsupported_flag") is True
        for row in unsupported
    )


def test_r3_tool_map_and_unrecognised() -> None:
    assert map_tool_name("Bash") == "Shell"
    assert map_tool_name("Agent") == "Task"
    assert map_tool_name("Edit") == "StrReplace"
    assert map_tool_name("NotARealTool") is None
    verdict = evaluate_pre_tool(
        {"tool_name": "NotARealTool", "tool_input": {}},
        REPO,
        map_tool_name=map_tool_name,
        evaluate_bound=lambda payload, root: type("R", (), {"verdict": "skip"})(),
    )
    assert verdict.verdict == "unrecognised"
    for host in ("Bash", "Agent", "Edit"):
        result = evaluate_pre_tool(
            {"tool_name": host, "tool_input": {}},
            REPO,
            map_tool_name=map_tool_name,
            evaluate_bound=lambda payload, root: type("R", (), {"verdict": "skip"})(),
        )
        assert result.verdict != "skip"
        assert result.verdict == "pass"


def test_r4_always_apply_skill_not_root_claude_md(tmp_path: Path) -> None:
    dist = REPO / "dist" / "claude-code"
    if not dist.is_dir():
        pytest.skip("dist/claude-code missing — generate first")
    assert not (dist / "CLAUDE.md").is_file()
    skill = dist / "skills" / "sw-always-apply" / "SKILL.md"
    assert skill.is_file()
    text = skill.read_text(encoding="utf-8")
    assert "sw-naming" in text or "alwaysApply" in text or "Shipwright" in text


def test_r5_stop_and_session_start_schemas() -> None:
    # Import adapter helpers
    sys.path.insert(0, str(REPO / "platforms" / "claude-code"))
    import hook_adapter

    session = hook_adapter._session_start_payload("hello")
    assert "event_name" not in session
    assert session.get("hookSpecificOutput", {}).get("hookEventName") == "SessionStart"
    assert session["hookSpecificOutput"].get("additionalContext") == "hello"
    # Stop must omit followup_message — empty object is the conforming shape.
    stop_doc = {}
    assert "followup_message" not in stop_doc
    assert "followup_message" not in stop_doc
