"""PRD 080 phase 16 — phase-mode context + non-environment harness predicate (R8).

ZOMBIES: Z absent state · O one worktree · M many siblings · S prior out-of-harness
scope set · E error/inertness / no ambient inference.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import wave_deliver_loop as wdl
import wave_failure as wf


def _capture_verify_env(
    monkeypatch: pytest.MonkeyPatch,
    *,
    harness: wf.HarnessHandle | None,
    ambient: dict[str, str] | None = None,
) -> dict[str, str]:
    captured: dict[str, str] = {}

    def _fake_run(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env") or {}
        captured.clear()
        captured.update({str(k): str(v) for k, v in env.items()})
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(wf, "verify_commands", lambda _root, scope="phase": ["true"])
    monkeypatch.setattr(wf, "verify_watchdog_max_minutes", lambda _root: None)
    monkeypatch.setattr(wf.subprocess, "run", _fake_run)
    if ambient:
        for key, value in ambient.items():
            monkeypatch.setenv(key, value)
    else:
        monkeypatch.delenv(wf.TEST_SCOPE_ENV, raising=False)
        monkeypatch.delenv("SW_HARNESS", raising=False)
    root = Path.cwd()
    outcome = wf.run_verify_suite(root, root, harness=harness, scope="phase")
    assert outcome["verdict"] == "pass"
    return captured


def test_absent_state_phase_mode_inactive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Z — no worktree state and no dispatch env → inactive despite ambient."""
    monkeypatch.setenv("SW_PHASE_MODE", "1")
    assert wdl.phase_mode_context_active(tmp_path) is False
    assert wdl.phase_mode_context_active(None) is False
    assert wdl.read_phase_mode_context(tmp_path) is None


def test_one_worktree_phase_mode_from_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O — single worktree with durable phaseMode context is active."""
    monkeypatch.delenv("SW_PHASE_MODE", raising=False)
    wdl.write_phase_mode_context(
        tmp_path,
        phase_id="16",
        phase_slug="phase-mode-context-and-harness-predicate-medium",
        task_list="docs/prds/080/tasks.md",
    )
    assert wdl.phase_mode_context_active(tmp_path) is True
    ctx = wdl.read_phase_mode_context(tmp_path)
    assert ctx is not None
    assert ctx["active"] is True
    assert ctx["phaseId"] == "16"
    assert ctx["phaseSlug"] == "phase-mode-context-and-harness-predicate-medium"


def test_many_sibling_worktrees_no_cross_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """M — sibling worktrees do not inherit each other's phase-mode context."""
    monkeypatch.setenv("SW_PHASE_MODE", "1")
    sibling_a = tmp_path / "a"
    sibling_b = tmp_path / "b"
    sibling_a.mkdir()
    sibling_b.mkdir()
    wdl.write_phase_mode_context(
        sibling_a,
        phase_id="16",
        phase_slug="phase-a",
        task_list="tasks.md",
    )
    assert wdl.phase_mode_context_active(sibling_a) is True
    assert wdl.phase_mode_context_active(sibling_b) is False

    dispatch_a = wdl.ship_loop_env_for_phase(
        {
            "source_task_list": "tasks.md",
            "phaseWorktrees": {"16": {"path": str(sibling_a)}},
        },
        "16",
        "phase-a",
    )
    parent = {"SW_PHASE_MODE": "1", "SW_PHASE_SLUG": "leaked", "PATH": "/bin", "HOME": str(tmp_path)}
    # Explicit dispatch without phase-mode must not inherit ambient bindings.
    child_b = wdl.build_ship_dispatch_child_env({"PYTHONPATH": "scripts"}, parent=parent)
    assert "SW_PHASE_MODE" not in child_b
    assert "SW_PHASE_SLUG" not in child_b
    child_a = wdl.build_ship_dispatch_child_env(
        dispatch_a,
        parent={"SW_PHASE_MODE": "0", "PATH": "/bin", "HOME": str(tmp_path)},
    )
    assert child_a.get("SW_PHASE_MODE") == "1"
    assert wdl.phase_mode_context_active(sibling_b, dispatch_env=child_b) is False
    assert wdl.phase_mode_context_active(sibling_a, dispatch_env=child_a) is True


def test_explicit_dispatch_env_activates_without_state(tmp_path: Path) -> None:
    """Explicit per-spawn dispatch env activates even when worktree state is absent."""
    assert wdl.phase_mode_context_active(tmp_path) is False
    assert (
        wdl.phase_mode_context_active(
            tmp_path,
            dispatch_env={"SW_PHASE_MODE": "1", "SW_PHASE_SLUG": "phase-x"},
        )
        is True
    )


def test_harness_scope_inert_without_handle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S/E — prior ambient SW_TEST_SCOPE / SW_HARNESS must not enable the switch."""
    env = _capture_verify_env(
        monkeypatch,
        harness=None,
        ambient={wf.TEST_SCOPE_ENV: "phase", "SW_HARNESS": "1"},
    )
    assert wf.TEST_SCOPE_ENV not in env
    # Env-probe forgery does not mint a handle.
    assert wf.is_harness_handle(None) is False
    assert wf.is_harness_handle("1") is False
    assert wf.is_harness_handle({"SW_HARNESS": "1"}) is False


def test_harness_scope_set_with_explicit_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Harness runner passes an explicit handle → SW_TEST_SCOPE is applied."""
    handle = wf.issue_harness_handle()
    assert wf.is_harness_handle(handle) is True
    env = _capture_verify_env(monkeypatch, harness=handle, ambient=None)
    assert env.get(wf.TEST_SCOPE_ENV) == "phase"
    assert wf.TEST_SCOPE_ENV.startswith("SW_TEST_")


def test_apply_harness_test_switches_keeps_sw_test_prefix() -> None:
    env: dict[str, str] = {}
    wf.apply_harness_test_switches(env, harness=wf.issue_harness_handle(), scope="full")
    assert list(env) == [wf.TEST_SCOPE_ENV]
    assert wf.TEST_SCOPE_ENV.startswith("SW_TEST_")
    assert env[wf.TEST_SCOPE_ENV] == "full"
    scrubbed: dict[str, str] = {wf.TEST_SCOPE_ENV: "phase"}
    wf.apply_harness_test_switches(scrubbed, harness=None, scope="phase")
    assert wf.TEST_SCOPE_ENV not in scrubbed


def test_ship_loop_env_writes_worktree_state(tmp_path: Path) -> None:
    wt = tmp_path / "phase-wt"
    wt.mkdir()
    state = {
        "source_task_list": "docs/prds/080/tasks.md",
        "phaseWorktrees": {"16": {"path": str(wt)}},
    }
    env = wdl.ship_loop_env_for_phase(state, "16", "phase-mode-context")
    assert env["SW_PHASE_MODE"] == "1"
    assert env["SW_PHASE_SLUG"] == "phase-mode-context"
    persisted = json.loads((wt / ".cursor" / "sw-worktree-state.json").read_text(encoding="utf-8"))
    assert persisted["phaseMode"]["active"] is True
    assert persisted["phaseMode"]["phaseSlug"] == "phase-mode-context"
