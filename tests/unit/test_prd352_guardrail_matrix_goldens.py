"""PRD 352 R18 — hook conformance goldens must match upstream shapes.

After R14–R17, emitters produce hookSpecificOutput nesting; these pins go green.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(REPO), str(REPO / "core"), str(REPO / "core" / "hooks")]

from adapters.claude_hook_helpers import build_claude_hook_response  # noqa: E402
from adapters.pre_tool_evaluator import (  # noqa: E402
    PreToolVerdict,
    _emit_submit_result,
    _session_start_payload,
    fail_closed_pretool_deny,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "guardrail-matrix"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_prd352_r18_session_start_uses_hook_specific_output() -> None:
    expected = _load("session-start.claude.expected.json")
    current = _session_start_payload("non-empty")
    assert "event_name" not in current
    assert "hookSpecificOutput" in current, (
        "SessionStart must emit hookSpecificOutput.hookEventName (upstream shape); "
        f"got keys={sorted(current)}"
    )
    assert (
        current["hookSpecificOutput"]["hookEventName"]
        == expected["hookSpecificOutput"]["hookEventName"]
    )
    assert current["hookSpecificOutput"]["additionalContext"]


def test_prd352_r18_pretool_allow_omits_decision_decision_field() -> None:
    expected = _load("pretool.claude.allow.expected.json")
    current = PreToolVerdict(verdict="pass").to_claude_hook_output()
    assert "decision" not in current or current.get("decision") is None
    assert (
        current.get("hookSpecificOutput", {}).get("permissionDecision")
        == expected["hookSpecificOutput"]["permissionDecision"]
    )


def test_prd352_r18_pretool_block_uses_permission_decision_deny() -> None:
    expected = _load("pretool.claude.block.expected.json")
    current = PreToolVerdict(verdict="fail", cause="blocked").to_claude_hook_output()
    assert (
        current.get("hookSpecificOutput", {}).get("permissionDecision")
        == expected["hookSpecificOutput"]["permissionDecision"]
    )


def test_prd352_r16_submit_allow_omits_decision() -> None:
    payload = _emit_submit_result(type("R", (), {"allow": True, "message": ""})())
    assert "decision" not in payload
    assert payload["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"


def test_prd352_r16_submit_block_uses_decision_block() -> None:
    payload = _emit_submit_result(type("R", (), {"allow": False, "message": "nope"})())
    assert payload.get("decision") == "block"
    assert payload.get("reason") == "nope"


def test_prd352_r17_fail_closed_deny() -> None:
    payload = fail_closed_pretool_deny("boom")
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "boom" in payload["hookSpecificOutput"]["permissionDecisionReason"]


def test_prd352_r14_helper_builds_nested_shape() -> None:
    out = build_claude_hook_response(
        hook_event_name="PreToolUse",
        permission_decision="allow",
    )
    assert out == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
        }
    }
