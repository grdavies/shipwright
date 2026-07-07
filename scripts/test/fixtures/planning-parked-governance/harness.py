#!/usr/bin/env python3
"""Parked-governance + scheduler-exhaustion fixture (PRD 057 R16, R28).

Proves, fully offline and deterministically:

1. **Unauthorized park refused** — a park by a non-allowlisted actor (or with no
   reason) is refused fail-closed and never mutates the park registry.
2. **Authorized park round-trip** — an allowlisted actor with a reason parks a
   unit; ``load_parked`` reflects it; unpark clears it.
3. **`next` skips unrunnable/parked units with reasons** — the file-path frontier
   scan skips parked and no-frozen-task-list units (emitting skip records) and
   selects the first runnable candidate instead of failing the whole frontier.
4. **All-parked/unrunnable frontier → scheduler-exhausted** — when every eligible
   candidate is parked or unrunnable, the scan yields no selection and the
   ``scheduler-exhausted`` halt payload names the parked/unrunnable units + the
   unpark remediation (distinct from failure and from silent empty output).
5. **Doctor over-parked-frontier drift finding** — the doctor surfaces an
   ``over-parked-frontier`` drift finding for the same condition.

No network, no git, no live issue store required.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_deliver_gate as pdg  # noqa: E402
import planning_graph as pg  # noqa: E402
import planning_park as park  # noqa: E402

ALLOWLIST_CFG = {"planning": {"scheduler": {"parkAllowlist": ["alice"]}}}


def _load_doctor():
    path = SCRIPTS / "planning-doctor.py"
    spec = importlib.util.spec_from_file_location("planning_doctor_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_unauthorized_park_refused() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        unauth = park.park_unit(root, "003-prd-legacy", reason="no runnable list", actor="mallory", cfg=ALLOWLIST_CFG)
        reasonless = park.park_unit(root, "003-prd-legacy", reason="", actor="alice", cfg=ALLOWLIST_CFG)
        mutated = bool(park.load_parked(root))
    ok = (
        unauth.get("verdict") == "refused"
        and unauth.get("halt") == "park-unauthorized"
        and reasonless.get("verdict") == "refused"
        and reasonless.get("halt") == "park-reason-required"
        and not mutated
    )
    return {"name": "unauthorized-park-refused", "ok": ok,
            "detail": f"unauth={unauth.get('halt')} reasonless={reasonless.get('halt')} mutated={mutated}"}


def check_authorized_park_roundtrip() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        parked = park.park_unit(root, "003-prd-legacy", reason="migrated legacy unit, no runnable task list",
                                actor="alice", cfg=ALLOWLIST_CFG)
        loaded = park.load_parked(root)
        unparked = park.unpark_unit(root, "003-prd-legacy", actor="alice", cfg=ALLOWLIST_CFG)
        after = park.load_parked(root)
    ok = (
        parked.get("verdict") == "pass"
        and "003-prd-legacy" in loaded
        and loaded["003-prd-legacy"].get("reason")
        and unparked.get("removed") is True
        and "003-prd-legacy" not in after
    )
    return {"name": "authorized-park-roundtrip", "ok": ok,
            "detail": f"parked={parked.get('verdict')} loaded={list(loaded)} after={list(after)}"}


def check_next_skips_unrunnable_with_reasons() -> dict:
    """scan_frontier skips parked + unrunnable, selects the first runnable (R16)."""
    root = Path("/nonexistent-fixture-root")
    parked = {"A": {"reason": "parked legacy", "actor": "alice"}}
    runnable = {"C": "docs/prds/C/tasks-C.md"}

    original = pdg.unit_runnable_or_skip
    try:
        def fake(root_arg, unit_id):
            task = runnable.get(unit_id)
            if task:
                return task, None
            return None, {"unitId": unit_id, "reason": "no-frozen-task-list"}
        pdg.unit_runnable_or_skip = fake
        selected, task_rel, skipped = pdg.scan_frontier(root, ["A", "B", "C"], parked)
    finally:
        pdg.unit_runnable_or_skip = original

    reasons = {s["unitId"]: s["reason"] for s in skipped}
    ok = (
        selected == "C"
        and task_rel == "docs/prds/C/tasks-C.md"
        and reasons.get("A") == "parked"
        and reasons.get("B") == "no-frozen-task-list"
    )
    return {"name": "next-skips-unrunnable-with-reasons", "ok": ok,
            "detail": f"selected={selected} skipped={reasons}"}


def check_all_parked_frontier_exhausted() -> dict:
    """Every eligible candidate parked/unrunnable → scheduler-exhausted halt (R28)."""
    root = Path("/nonexistent-fixture-root")
    parked = {"A": {"reason": "parked legacy", "actor": "alice"}}

    original = pdg.unit_runnable_or_skip
    try:
        def fake(root_arg, unit_id):
            # B has no frozen task list (unrunnable); A is handled as parked.
            return None, {"unitId": unit_id, "reason": "no-frozen-task-list"}
        pdg.unit_runnable_or_skip = fake
        selected, task_rel, skipped = pdg.scan_frontier(root, ["A", "B"], parked)
    finally:
        pdg.unit_runnable_or_skip = original

    payload = park.scheduler_exhausted_payload(source="file", eligible=["A", "B"], skipped=skipped)
    ok = (
        selected is None
        and task_rel is None
        and payload.get("verdict") == "halt"
        and payload.get("halt") == "scheduler-exhausted"
        and payload.get("parkedUnits") == ["A"]
        and payload.get("unrunnableUnits") == ["B"]
        and bool(payload.get("remediation"))
        and park.SCHEDULER_EXHAUSTED_EXIT == 40
    )
    return {"name": "all-parked-frontier-scheduler-exhausted", "ok": ok,
            "detail": f"halt={payload.get('halt')} parked={payload.get('parkedUnits')} unrunnable={payload.get('unrunnableUnits')}"}


def check_doctor_over_parked_finding() -> dict:
    """Doctor surfaces an over-parked-frontier drift finding (R28)."""
    doctor = _load_doctor()
    root = Path("/nonexistent-fixture-root")
    saved = (pg.discover_units, pg.order_eligible, pdg.task_list_for_unit, park.load_parked)
    try:
        pg.discover_units = lambda r: []
        pg.order_eligible = lambda units: ["A", "B"]
        park.load_parked = lambda r: {"A": {"reason": "parked", "actor": "alice"}}
        pdg.task_list_for_unit = lambda r, unit_id: None  # B unrunnable
        finding = doctor.parked_frontier_finding(root)
    finally:
        pg.discover_units, pg.order_eligible, pdg.task_list_for_unit, park.load_parked = saved

    ok = (
        isinstance(finding, dict)
        and finding.get("check") == "over-parked-frontier"
        and finding.get("status") == "drift"
        and finding.get("parkedUnits") == ["A"]
        and finding.get("unrunnableUnits") == ["B"]
        and bool(finding.get("remediation"))
    )
    return {"name": "doctor-over-parked-frontier-drift", "ok": ok, "detail": finding}


def main() -> int:
    checks = [
        check_unauthorized_park_refused(),
        check_authorized_park_roundtrip(),
        check_next_skips_unrunnable_with_reasons(),
        check_all_parked_frontier_exhausted(),
        check_doctor_over_parked_finding(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-parked-governance",
        "rid": "R28",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
