#!/usr/bin/env python3
"""`effective-backend` kill-switch + per-wave rollback fixture (PRD 057 R31).

Exercises the full wave-rollback contract against a hermetic
``SW_ISSUES_FIXTURE=1`` in-memory issue store (no network, no real repo
mutation — everything runs inside a temp directory):

1. ``SW_PLANNING_KILL_SWITCH`` forces ``effective-backend`` resolution back to
   the file-store default regardless of the configured ``issue-store``
   backend; clearing the env var restores the prior (issue-store) behavior.
2. An explicit ``--backend``/``override`` argument (used internally by
   ``materialize_from_store``) bypasses the kill-switch so rollback tooling can
   still read the authoritative store while the switch is active.
3. ``wave_regression_finding`` detects drift between a local file-store
   projection and the issue store while the kill-switch is active, is inert
   (``None``) once the switch is off, and reports clean after
   ``materialize_from_store`` re-syncs.
4. ``materialize_from_store`` is idempotent and never mutates or deletes
   issue-store data (re-materializing twice yields identical hashes and an
   unchanged store fingerprint).
5. ``planning-doctor.py`` surfaces the drift as a fail-closed ``wave-regression``
   finding.

ZOMBIES: Interfaces (effective-backend kill-switch) · Exceptions
(``wave-regression`` on drift) · State (re-materialize from store) ·
Idempotency (no data loss).
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_store as ps

UNIT_ID = "rollback-fixture"
BODY_PATH = "docs/prds/999-rollback/999-prd-rollback.md"


def _load_module(rel_path: str, name: str) -> ModuleType:
    path = ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_cfg_dict() -> dict:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "wave-rollback-fixture",
                "waveRollback": {"trackedUnits": [{"unitId": UNIT_ID, "bodyPath": BODY_PATH}]},
            }
        },
        "host": {"provider": "github"},
    }


def _setup_root(tmp: str) -> Path:
    root = Path(tmp)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_synthetic_cfg_dict(), indent=2), encoding="utf-8")
    return root


@contextlib.contextmanager
def _env_flag(name: str, active: bool):
    prior = os.environ.get(name)
    if active:
        os.environ[name] = "1"
    else:
        os.environ.pop(name, None)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = prior


def kill_switch(active: bool):
    return _env_flag(ps.KILL_SWITCH_ENV, active)


def fixture_issue_store():
    return _env_flag("SW_ISSUES_FIXTURE", True)


def check_kill_switch_forces_file_store_and_restores() -> dict:
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        with kill_switch(True):
            on = ps.resolve_effective_backend(root, cfg)
        with kill_switch(False):
            off = ps.resolve_effective_backend(root, cfg)
    ok = (
        on.get("effective") == "in-repo-public"
        and on.get("killSwitch") is True
        and on.get("fallbackReason") == "kill-switch"
        and off.get("effective") == "issue-store"
        and off.get("killSwitch") is None
    )
    return {
        "name": "kill-switch-forces-file-store-and-restores",
        "ok": ok,
        "detail": f"on={on} off={off}",
    }


def check_override_bypasses_kill_switch() -> dict:
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store(), kill_switch(True):
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        effective = ps.resolve_effective_backend(root, cfg, override="issue-store")
        backend = ps.get_backend(root, cfg, override="issue-store")
    ok = effective.get("effective") == "issue-store" and isinstance(backend, ps.IssueStoreBackend)
    return {
        "name": "override-bypasses-kill-switch",
        "ok": ok,
        "detail": f"effective={effective} backendType={type(backend).__name__}",
    }


def check_wave_regression_detects_drift_then_clean() -> dict:
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)

        issue_backend = ps.get_backend(root, cfg, override="issue-store")
        issue_backend.put(UNIT_ID, BODY_PATH, "# rollback fixture v1 (authoritative)")
        local_backend = ps.InRepoPublicBackend(root, cfg)
        # Seed the local projection identical to the store first, so the
        # "in-sync" baseline is a genuine content match rather than a
        # trivially-missing local file (which would itself be drift).
        local_backend.put(UNIT_ID, BODY_PATH, "# rollback fixture v1 (authoritative)")

        with kill_switch(True):
            clean_baseline = ps.wave_regression_finding(root, cfg)

            local_backend.put(UNIT_ID, BODY_PATH, "# STALE local copy pre-rollback")

            finding_drift = ps.wave_regression_finding(root, cfg)

            mat_result = ps.materialize_from_store(root, cfg, [{"unitId": UNIT_ID, "bodyPath": BODY_PATH}])

            finding_clean = ps.wave_regression_finding(root, cfg)

        with kill_switch(False):
            finding_inert_switch_off = ps.wave_regression_finding(root, cfg)

    ok = (
        clean_baseline is not None and clean_baseline.get("status") == "ok"
        and finding_drift is not None and finding_drift.get("status") == "drift"
        and len(finding_drift.get("driftedUnits") or []) == 1
        and mat_result.get("verdict") == "ok"
        and mat_result.get("dataLoss") is False
        and finding_clean is not None and finding_clean.get("status") == "ok"
        and finding_inert_switch_off is None
    )
    return {
        "name": "wave-regression-detects-drift-then-clean",
        "ok": ok,
        "detail": (
            f"cleanBaseline={clean_baseline} drift={finding_drift} "
            f"materialize={mat_result} clean={finding_clean} switchOff={finding_inert_switch_off}"
        ),
    }


def check_materialize_from_store_idempotent_no_data_loss() -> dict:
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        issue_backend = ps.get_backend(root, cfg, override="issue-store")
        issue_backend.put(UNIT_ID, BODY_PATH, "# idempotency check v1")
        units = [{"unitId": UNIT_ID, "bodyPath": BODY_PATH}]

        with kill_switch(True):
            before = issue_backend.get(UNIT_ID, BODY_PATH)
            first = ps.materialize_from_store(root, cfg, units)
            mid = issue_backend.get(UNIT_ID, BODY_PATH)
            second = ps.materialize_from_store(root, cfg, units)
            after = issue_backend.get(UNIT_ID, BODY_PATH)
            local_backend = ps.InRepoPublicBackend(root, cfg)
            local_content = local_backend.get(UNIT_ID, BODY_PATH)

    ok = (
        first.get("verdict") == "ok"
        and second.get("verdict") == "ok"
        and first["results"][0]["hash"] == second["results"][0]["hash"]
        and before.hash == mid.hash == after.hash
        and local_content.content == "# idempotency check v1"
    )
    return {
        "name": "materialize-from-store-idempotent-no-data-loss",
        "ok": ok,
        "detail": f"before={before.hash} mid={mid.hash} after={after.hash} local={local_content.content!r}",
    }


def check_doctor_reports_wave_regression_fail_closed() -> dict:
    doctor = _load_module("scripts/planning-doctor.py", "_wave_rollback_doctor")
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        issue_backend = ps.get_backend(root, cfg, override="issue-store")
        issue_backend.put(UNIT_ID, BODY_PATH, "# doctor drift check v1")
        with kill_switch(True):
            local_backend = ps.InRepoPublicBackend(root, cfg)
            local_backend.put(UNIT_ID, BODY_PATH, "# doctor drift check STALE")
            out = doctor.doctor(root, sweep=False)
    ok = out.get("verdict") == "fail" and "wave-regression" in (out.get("warnings") or [])
    return {
        "name": "doctor-reports-wave-regression-fail-closed",
        "ok": ok,
        "detail": f"verdict={out.get('verdict')} warnings={out.get('warnings')}",
    }


def main() -> int:
    checks = [
        check_kill_switch_forces_file_store_and_restores(),
        check_override_bypasses_kill_switch(),
        check_wave_regression_detects_drift_then_clean(),
        check_materialize_from_store_idempotent_no_data_loss(),
        check_doctor_reports_wave_regression_fail_closed(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-wave-rollback",
        "rid": "R31",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
