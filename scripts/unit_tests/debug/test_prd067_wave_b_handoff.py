"""PRD 067 Wave B debug→deliver handoff regressions."""
from __future__ import annotations

import json
from pathlib import Path

from debug_deliver_handoff import (
    assert_pre_confirm_forbidden,
    materialize_debug_pack,
    unit_id_for,
)


def test_materialize_writes_tasks_debug_pack(tmp_path: Path) -> None:
    out = materialize_debug_pack(
        tmp_path,
        slug="Null-Pointer!",
        title="Guard null",
        files=["scripts/foo.py"],
        acceptance=["regression green"],
        rca_summary="redacted",
    )
    assert out["verdict"] == "ok"
    assert out["unitId"] == "tasks-debug-null-pointer"
    assert out["resumeCommand"].startswith("/sw-deliver run --unit-id ")
    path = tmp_path / out["materializedPath"]
    assert path.is_file()
    body = path.read_text(encoding="utf-8")
    assert "frozen: true" in body
    assert "### 1." in body
    assert out["handoff"]["taskSpawnDeliverForbidden"] is True


def test_pre_confirm_guard_blocks_execute() -> None:
    bad = assert_pre_confirm_forbidden("sw-execute")
    assert bad["verdict"] == "fail"
    good = assert_pre_confirm_forbidden("rca")
    assert good["verdict"] == "pass"


def test_unit_id_grammar() -> None:
    assert unit_id_for("foo-bar") == "tasks-debug-foo-bar"


def test_debug_pack_forbids_execute_before_confirm() -> None:
    pack = json.loads(
        Path("core/sw-reference/guidelines/debug.pack.json").read_text(encoding="utf-8")
    )
    # Parity with orchestrator-step-plan.forbiddenSteps (lint-enforced)
    assert "sw-execute" in pack.get("forbiddenDeliverOnlySteps", [])
    assert "segments" in pack
    assert "sw-ship" in pack["segments"]["diagnosis"]["forbiddenSteps"]
