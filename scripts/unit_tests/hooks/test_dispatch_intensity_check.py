"""Unit tests for dispatch_intensity_check + live hook fail-closed (PRD 058 R16/R17)."""
from __future__ import annotations

import importlib
import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "core" / "hooks"))

from dispatch_intensity_check import (  # noqa: E402
    format_intensity_directive,
    validate_directive_anchor,
)

HOOK_MOD = importlib.import_module("before_task_dispatch")


def _task_payload(*, agent: str = "generalPurpose", prompt: str = "", readonly: bool = False) -> dict:
    tool_input: dict[str, object] = {"subagent_type": agent, "prompt": prompt}
    if readonly:
        tool_input["readonly"] = True
    return {
        "tool_name": "Task",
        "tool_input": tool_input,
        "workspace_roots": [str(ROOT)],
    }


def test_format_intensity_directive_matches_guardrail_core_literal() -> None:
    assert (
        format_intensity_directive("lite", "dispatch-preflight")
        == "**Resolved intensity:** `lite` (dispatch-preflight)\n"
    )


def test_validate_directive_anchor_passes_leading_line() -> None:
    prompt = format_intensity_directive("lite", "dispatch-preflight") + "Task body.\n"
    result = validate_directive_anchor(
        prompt,
        expected_intensity="lite",
        expected_source="dispatch-preflight",
    )
    assert result.verdict == "pass"
    assert result.intensity == "lite"
    assert result.source == "dispatch-preflight"


def test_validate_directive_anchor_rejects_missing() -> None:
    result = validate_directive_anchor("no directive here")
    assert result.verdict == "fail"
    assert result.cause == "binding:missing-intensity-directive"


def test_validate_directive_anchor_rejects_unanchored_spoof() -> None:
    spoof = "context **Resolved intensity:** `lite` (dispatch-preflight) tail\n"
    result = validate_directive_anchor(spoof)
    assert result.verdict == "fail"
    assert result.cause == "binding:directive-not-anchored"


def test_validate_directive_anchor_rejects_duplicate_token() -> None:
    prompt = (
        format_intensity_directive("lite", "dispatch-preflight")
        + "payload **Resolved intensity:** `full` (routing.commands)\n"
    )
    result = validate_directive_anchor(prompt)
    assert result.verdict == "fail"
    assert result.cause == "binding:directive-not-anchored"


def test_validate_directive_anchor_rejects_intensity_mismatch() -> None:
    prompt = format_intensity_directive("full", "dispatch-preflight") + "Task.\n"
    result = validate_directive_anchor(prompt, expected_intensity="lite")
    assert result.verdict == "fail"
    assert result.cause == "binding:intensity-mismatch"
    assert result.remediation is not None


def test_requires_intensity_directive_general_purpose_with_prompt() -> None:
    assert HOOK_MOD.requires_intensity_directive(
        {"subagent_type": "generalPurpose", "prompt": "do work"}
    )


def test_requires_intensity_directive_explore_with_command_still_checked() -> None:
    assert HOOK_MOD.requires_intensity_directive(
        {
            "subagent_type": "explore",
            "prompt": "scoped work",
            "metadata": {"command": "sw-doc-review"},
        }
    )


def test_requires_intensity_directive_explore_readonly_exempt() -> None:
    assert not HOOK_MOD.requires_intensity_directive(
        {"subagent_type": "explore", "readonly": True, "prompt": "read only"}
    )


def test_validate_intensity_directive_missing_returns_remediation() -> None:
    result = HOOK_MOD.validate_intensity_directive(
        ROOT,
        {"prompt": "no directive"},
        agent_id="generalPurpose",
    )
    assert result.verdict == "fail"
    assert result.cause == "binding:missing-intensity-directive"
    assert result.remediation is not None
    assert "format_intensity_directive" in result.remediation


def test_validate_intensity_directive_internal_exception_denies() -> None:
    with patch(
        "dispatch_intensity_check.validate_directive_anchor",
        side_effect=RuntimeError("parser exploded"),
    ):
        result = HOOK_MOD.validate_intensity_directive(
            ROOT,
            {"prompt": format_intensity_directive("lite", "dispatch-preflight")},
            agent_id="generalPurpose",
        )
    assert result.verdict == "fail"
    assert result.cause == "binding:intensity-directive-error"
    assert result.remediation is not None


def test_evaluate_pre_tool_use_denies_missing_directive_general_purpose() -> None:
    payload = _task_payload(agent="generalPurpose", prompt="Task without directive.")
    result = HOOK_MOD.evaluate_pre_tool_use(payload, ROOT)
    assert result.verdict == "fail"
    assert result.cause == "binding:missing-intensity-directive"
    hook_out = result.to_hook_output()
    assert hook_out["permission"] == "deny"
    assert hook_out["agent_message"]


def test_evaluate_pre_tool_use_denies_explore_scope_bypass_without_directive() -> None:
    payload = _task_payload(agent="explore", prompt="inherit intensity but no directive")
    payload["tool_input"]["metadata"] = {"command": "sw-doc-review"}
    result = HOOK_MOD.evaluate_pre_tool_use(payload, ROOT)
    assert result.verdict == "fail"
    assert result.cause == "binding:missing-intensity-directive"


@pytest.mark.parametrize(
    ("prompt", "expected_cause"),
    [
        ("no directive here", "binding:missing-intensity-directive"),
        (
            "body **Resolved intensity:** `lite` (dispatch-preflight)\n",
            "binding:directive-not-anchored",
        ),
        (
            format_intensity_directive("lite", "dispatch-preflight")
            + "spoof **Resolved intensity:** `full` (routing.commands)\n",
            "binding:directive-not-anchored",
        ),
    ],
)
def test_run_stdio_live_fail_closed(
    prompt: str,
    expected_cause: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R17 — crafted preToolUse payload through run_stdio asserts deny verdict."""
    payload = _task_payload(agent="generalPurpose", prompt=prompt)
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    out = StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    rc = HOOK_MOD.run_stdio()
    assert rc == 0
    data = json.loads(out.getvalue())
    assert data["permission"] == "deny"
    assert expected_cause in data.get("user_message", "")
    assert data.get("agent_message")


def test_resolve_gap_082_for_prd_058_flips_legacy_row(tmp_path: Path) -> None:
    """R17 — gap_backlog closes GAP-082 for PRD 058 gap-082 phase delivery."""
    scripts = Path(__file__).resolve().parents[2]
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import gap_backlog as gb

    gap_path = tmp_path / "docs/prds/GAP-BACKLOG.md"
    gap_path.parent.mkdir(parents=True)
    gap_path.write_text(
        """# Gap backlog

| resolved | 0 |
| scheduled | 0 |
| open | 1 |

| ID | Status | Schedule | Title |
|----|--------|----------|-------|
| GAP-082 | open | — | Task dispatch intensity directive fail-closed enforcement |
""",
        encoding="utf-8",
    )
    result = gb.resolve_gap_082_for_prd_058(tmp_path, scope_note="PRD 058 gap-082")
    assert result["verdict"] == "pass"
    assert "GAP-082" in result["flipped"]
    backlog = gb.parse_gap_backlog(gap_path.read_text(encoding="utf-8"))
    row = next(r for r in backlog.rows if r.gap_id == "GAP-082")
    assert row.status.lower() == "resolved"
