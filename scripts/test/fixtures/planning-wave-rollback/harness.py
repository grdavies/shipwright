#!/usr/bin/env python3
"""`effective-backend` durable disable + legacy shim rollback fixture (PRD 057 R31 / PRD 080 R8).

Exercises the full wave-rollback contract against a hermetic
``SW_ISSUES_FIXTURE=1`` in-memory issue store (no network, no real repo
mutation — everything runs inside a temp directory):

1. Durable disable (``planning_backend_control.cmd_disable``) forces
   ``effective-backend`` resolution back to the file-store default regardless of
   the configured ``issue-store`` backend; ``cmd_enable`` restores issue-store.
2. An explicit ``--backend``/``override`` argument (used internally by
   ``materialize_from_store``) bypasses durable disable so rollback tooling can
   still read the authoritative store while disable is active.
3. Legacy ``SW_PLANNING_KILL_SWITCH`` is a warn-only shim: alone it cannot force
   file-store fallback; with a durable record present it still cannot change
   resolution and surfaces ``legacyShimWarnings``.
4. ``wave_regression_finding`` detects drift between a local file-store
   projection and the issue store while disable is active, is inert
   (``None``) once disable is off, and reports clean after
   ``materialize_from_store`` re-syncs.
5. ``materialize_from_store`` is idempotent and never mutates or deletes
   issue-store data (re-materializing twice yields identical hashes and an
   unchanged store fingerprint).
6. ``planning-doctor.py`` surfaces the drift as a fail-closed ``wave-regression``
   finding.

ZOMBIES: Interfaces (durable disable + legacy shim) · Exceptions
(``wave-regression`` on drift) · State (re-materialize from store) ·
Idempotency (no data loss).
"""
from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import ModuleType

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_backend_control as pbc
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
    subprocess.run(["git", "init", "-b", "main"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/wave-rollback-fixture.git"],
        cwd=root,
        check=True,
        capture_output=True,
    )
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


@contextlib.contextmanager
def durable_disable(root: Path, active: bool):
    """Durable disable-record path (PRD 080 phase 15 / R8)."""
    if active:
        pbc.cmd_disable(root, set_by="fixture", reason="wave rollback")
    try:
        yield
    finally:
        if active:
            pbc.cmd_enable(root)


# Back-compat alias used by older call sites / docs.
kill_switch = durable_disable


@contextlib.contextmanager
def legacy_kill_switch_shim(active: bool):
    """Legacy ``SW_PLANNING_KILL_SWITCH`` warn-only shim path (PRD 080 R8)."""
    with _env_flag(pbc.LEGACY_KILL_SWITCH_ENV, active):
        yield


def fixture_issue_store():
    return _env_flag("SW_ISSUES_FIXTURE", True)


def check_kill_switch_forces_file_store_and_restores() -> dict:
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        with durable_disable(root, True):
            on = ps.resolve_effective_backend(root, cfg)
        with durable_disable(root, False):
            off = ps.resolve_effective_backend(root, cfg)
    ok = (
        on.get("effective") == "issue-store"
        and on.get("configured") == "issue-store"
        and on.get("killSwitch") is True
        and on.get("fallbackReason") == "kill-switch"
        and on.get("authorityState") == "read-only"
        and off.get("effective") == "issue-store"
        and off.get("killSwitch") is None
    )
    return {
        "name": "kill-switch-forces-file-store-and-restores",
        "ok": ok,
        "detail": f"on={on} off={off}",
    }


def check_override_bypasses_kill_switch() -> dict:
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        with durable_disable(root, True):
            effective = ps.resolve_effective_backend(root, cfg, override="issue-store")
            backend = ps.get_backend(root, cfg, override="issue-store")
    ok = effective.get("effective") == "issue-store" and isinstance(backend, ps.IssueStoreBackend)
    return {
        "name": "override-bypasses-kill-switch",
        "ok": ok,
        "detail": f"effective={effective} backendType={type(backend).__name__}",
    }


def check_legacy_shim_inert_without_durable_record() -> dict:
    """Legacy env alone must not force file-store fallback (warn-only shim)."""
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        with legacy_kill_switch_shim(True):
            resolved = ps.resolve_effective_backend(root, cfg)
            notices = pbc.legacy_kill_switch_env_shim()
    ok = (
        resolved.get("effective") == "issue-store"
        and resolved.get("killSwitch") is None
        and bool(notices)
    )
    return {
        "name": "legacy-shim-inert-without-durable-record",
        "ok": ok,
        "detail": f"resolved={resolved} notices={notices}",
    }


def check_legacy_shim_with_durable_record_surfaces_warnings() -> dict:
    """Durable record drives fallback; legacy shim only attaches warnings."""
    with tempfile.TemporaryDirectory() as tmp, fixture_issue_store():
        root = _setup_root(tmp)
        cfg = ps.load_workflow_config(root)
        with durable_disable(root, True), legacy_kill_switch_shim(True):
            resolved = ps.resolve_effective_backend(root, cfg)
    ok = (
        resolved.get("effective") == "issue-store"
        and resolved.get("configured") == "issue-store"
        and resolved.get("killSwitch") is True
        and bool(resolved.get("legacyShimWarnings"))
    )
    return {
        "name": "legacy-shim-with-durable-record-surfaces-warnings",
        "ok": ok,
        "detail": f"resolved={resolved}",
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

        with durable_disable(root, True):
            clean_baseline = ps.wave_regression_finding(root, cfg)

            local_backend.put(UNIT_ID, BODY_PATH, "# STALE local copy pre-rollback")

            finding_drift = ps.wave_regression_finding(root, cfg)

            mat_result = ps.materialize_from_store(root, cfg, [{"unitId": UNIT_ID, "bodyPath": BODY_PATH}])

            finding_clean = ps.wave_regression_finding(root, cfg)

        with durable_disable(root, False):
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

        with durable_disable(root, True):
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
        with durable_disable(root, True):
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
        check_legacy_shim_inert_without_durable_record(),
        check_legacy_shim_with_durable_record_surfaces_warnings(),
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
