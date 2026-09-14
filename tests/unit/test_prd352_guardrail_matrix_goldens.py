"""PRD 352 R18 — hook conformance goldens must match upstream shapes.

Expected red until R14–R17 rewrite Claude hook payloads to hookSpecificOutput nesting.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "guardrail-matrix"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_prd352_r18_session_start_uses_hook_specific_output() -> None:
    """Current SessionStart emitters invent event_name; golden requires hookSpecificOutput."""
    expected = _load("session-start.claude.expected.json")
    # Simulate current (wrong) emitter shape — pin the defect.
    current = {"event_name": "SessionStart", "additionalContext": "x"}
    assert "hookSpecificOutput" in current, (
        "SessionStart must emit hookSpecificOutput.hookEventName (upstream shape); "
        f"got keys={sorted(current)} expected keys including hookSpecificOutput"
    )
    assert current["hookSpecificOutput"]["hookEventName"] == expected["hookSpecificOutput"]["hookEventName"]


def test_prd352_r18_pretool_allow_omits_decision_decision_field() -> None:
    expected = _load("pretool.claude.allow.expected.json")
    current = {"decision": "approve", "hookSpecificOutput": {"hookEventName": "PreToolUse"}}
    assert "decision" not in current or current.get("decision") is None
    assert current.get("hookSpecificOutput", {}).get("permissionDecision") == expected["hookSpecificOutput"]["permissionDecision"]


def test_prd352_r18_pretool_block_uses_permission_decision_deny() -> None:
    expected = _load("pretool.claude.block.expected.json")
    current = {"decision": "block"}
    assert current.get("hookSpecificOutput", {}).get("permissionDecision") == expected["hookSpecificOutput"]["permissionDecision"]
