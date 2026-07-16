"""PRD 070 phase 4 — in-session self-wake close-out fast-path tests."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc

SHA = "a" * 40
PRD_UNIT = "prd-070-automated-delivery-closeout"
RUN_ID = "sw-deliver-070-automated-delivery-closeout"
OTHER_RUN_ID = "sw-deliver-070-other-delivery"


def _pending_merge_state(*, slug: str = "automated-delivery-closeout") -> dict:
    return {
        "prd_number": "070",
        "target": {"branch": f"feat/{slug}", "slug": slug},
        "completion": {"status": "completed-pending-merge"},
        "source_task_list": "docs/prds/070-automated-delivery-closeout/tasks-070-automated-delivery-closeout.md",
        "terminalPr": {"number": 99},
    }


def _write_state(tmp_path: Path, slug: str, state: dict) -> None:
    cursor = tmp_path / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    (cursor / f"sw-deliver-state.{slug}.json").write_text(json.dumps(state), encoding="utf-8")


def test_deliver_run_id_from_state() -> None:
    state = _pending_merge_state()
    assert dc.deliver_run_id_from_state(state) == RUN_ID


def test_self_wake_poll_waits_without_pending_merge(tmp_path: Path) -> None:
    state = {"prd_number": "070", "target": {"slug": "automated-delivery-closeout"}}
    _write_state(tmp_path, "automated-delivery-closeout", state)

    def probe(_root, _state):
        return {"merged": True, "mergeCommit": SHA}

    result = dc.self_wake_poll_once(tmp_path, RUN_ID, merge_probe=probe)
    assert result["verdict"] == "wait"
    assert result["completionGate"] == "not-pending-merge"


def test_self_wake_closes_on_in_session_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _pending_merge_state()
    _write_state(tmp_path, "automated-delivery-closeout", state)

    def probe(_root, _state):
        return {"merged": True, "mergeCommit": SHA, "prNumber": 99}

    close_calls: list[dict] = []

    def fake_run_closeout(root, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
        close_calls.append(
            {"prd_unit_id": prd_unit_id, "merge_sha": merge_sha, "pr_number": pr_number}
        )
        return {
            "verdict": "ready",
            "action": "run-closeout",
            "closure": {"closureAudit": {"verdict": "ready"}},
        }

    monkeypatch.setattr(dc, "run_closeout", fake_run_closeout)

    result = dc.self_wake_poll_once(tmp_path, RUN_ID, merge_probe=probe)
    assert result["verdict"] == "ready"
    assert result["action"] == "self-wake-closeout"
    assert close_calls == [
        {"prd_unit_id": PRD_UNIT, "merge_sha": SHA, "pr_number": 99}
    ]
    marker = dc.load_close_marker(tmp_path, PRD_UNIT)
    assert marker is not None
    assert marker["mergeSha"] == SHA


def test_second_trigger_is_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = _pending_merge_state()
    _write_state(tmp_path, "automated-delivery-closeout", state)
    dc.write_close_marker(tmp_path, PRD_UNIT, SHA, audit={"verdict": "ready"})

    def probe(_root, _state):
        return {"merged": True, "mergeCommit": SHA}

    def fail_if_called(*_a, **_k):
        raise AssertionError("run_closeout should not run on short-circuit")

    monkeypatch.setattr(dc, "run_closeout", fail_if_called)
    monkeypatch.setattr(
        "planning_store.audit_closure_completeness",
        lambda *_a, **_k: {"verdict": "ready"},
    )

    result = dc.self_wake_poll_once(tmp_path, RUN_ID, merge_probe=probe)
    assert result["verdict"] == "ready"
    assert result["noop"] is True


def test_concurrent_runs_select_correct_target_by_run_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_a = _pending_merge_state(slug="automated-delivery-closeout")
    state_b = _pending_merge_state(slug="other-delivery")
    state_b["source_task_list"] = "docs/prds/070-other-delivery/tasks-070-other-delivery.md"
    _write_state(tmp_path, "automated-delivery-closeout", state_a)
    _write_state(tmp_path, "other-delivery", state_b)

    seen: list[str] = []

    def probe(_root, state):
        seen.append(dc.deliver_run_id_from_state(state) or "")
        return {"merged": True, "mergeCommit": SHA, "prNumber": 42}

    def fake_run_closeout(root, *, prd_unit_id, merge_sha, pr_number=None, dry_run=False, state=None):
        return {
            "verdict": "ready",
            "action": "run-closeout",
            "prdUnitId": prd_unit_id,
            "closure": {"closureAudit": {"verdict": "ready"}},
        }

    monkeypatch.setattr(dc, "run_closeout", fake_run_closeout)

    result = dc.self_wake_poll_once(tmp_path, OTHER_RUN_ID, merge_probe=probe)
    assert result["verdict"] == "ready"
    assert seen == [OTHER_RUN_ID]
    assert result["prdUnitId"] == "prd-070-other-delivery"
