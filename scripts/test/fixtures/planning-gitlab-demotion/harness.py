#!/usr/bin/env python3
"""gitlab-issues demotion / fail-closed harness (PRD 057 R7 / D1).

Proves the R7 disposition (gap-039): ``gitlab-issues`` is removed from the
shipped issue-provider set and demoted to a deferred, fail-closed state until a
live ``planning_gitlab_client.py`` adapter ships in a follow-up unit.

Checks (all deterministic, offline):
1. ``gitlab-issues`` is ABSENT from ``planning_store.SHIPPED_ISSUES_PROVIDERS``
   and marked deferred in ``planning_store.DEFERRED_ISSUES_PROVIDERS`` /
   ``issues_lib.DEFERRED_ISSUES_PROVIDERS``.
2. ``gitlab-issues`` remains a *known* provider (still in ``ISSUES_PROVIDERS``)
   so config validation keeps recognizing it — it is deferred, not unknown.
3. Selecting ``gitlab-issues`` for a live backend fails closed with a clear
   operator message (``IssueCapabilityError`` naming the deferral + follow-up).
4. Effective-backend resolution under an issue-store config that selects
   ``gitlab-issues`` reports ``shipped: False`` and yields the
   ``issues-provider-not-shipped`` fail-closed fallback reason.

ZOMBIES: Zero (provider unimplemented) · Interfaces (fail-closed message) ·
Exceptions (selection refused) · State (demoted to deferred).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import issues_lib
import planning_store

PROVIDER = "gitlab-issues"


def check_absent_from_shipped() -> dict:
    shipped = planning_store.SHIPPED_ISSUES_PROVIDERS
    deferred_store = planning_store.DEFERRED_ISSUES_PROVIDERS
    deferred_lib = issues_lib.DEFERRED_ISSUES_PROVIDERS
    ok = (
        PROVIDER not in shipped
        and PROVIDER in deferred_store
        and PROVIDER in deferred_lib
    )
    return {
        "name": "gitlab-absent-from-shipped",
        "ok": ok,
        "detail": f"shipped={sorted(shipped)} deferred(store)={sorted(deferred_store)} "
        f"deferred(lib)={sorted(deferred_lib)}",
    }


def check_still_known() -> dict:
    ok = PROVIDER in planning_store.ISSUES_PROVIDERS
    return {
        "name": "gitlab-still-known-provider",
        "ok": ok,
        "detail": f"known providers={sorted(planning_store.ISSUES_PROVIDERS)}",
    }


def check_live_backend_fails_closed() -> dict:
    """Selecting gitlab-issues for a live (non-fixture) backend must fail closed."""
    # Force non-fixture mode so the deferred branch is exercised (CI may set
    # SW_ISSUES_FIXTURE=1 for hermetic runs, which would otherwise short-circuit
    # to the fixture store before provider selection).
    saved = os.environ.pop("SW_ISSUES_FIXTURE", None)
    raised = False
    message = ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            client = issues_lib.IssuesClient(Path(tmp), PROVIDER)
            try:
                client._live_backend()
            except issues_lib.IssueCapabilityError as exc:
                raised = True
                message = str(exc)
    finally:
        if saved is not None:
            os.environ["SW_ISSUES_FIXTURE"] = saved
    lowered = message.lower()
    clear = raised and "deferred" in lowered and "fail-closed" in lowered and (
        "follow-up" in lowered or "planning_gitlab_client" in lowered
    )
    return {
        "name": "gitlab-live-backend-fails-closed",
        "ok": clear,
        "detail": f"raised={raised} message={message!r}",
    }


def check_resolution_reports_not_shipped() -> dict:
    """Config resolution surfaces gitlab-issues as supported-but-not-shipped."""
    cfg = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": PROVIDER,
                "issues": {"tokenEnv": "ISSUES_GITLAB_TOKEN"},
            }
        }
    }
    resolved = planning_store.resolve_issues_provider(cfg)
    with tempfile.TemporaryDirectory() as tmp:
        reason = planning_store.issue_store_fallback_reason(Path(tmp), cfg)
    ok = (
        resolved.get("provider") == PROVIDER
        and resolved.get("supported") is True
        and resolved.get("shipped") is False
        and reason == "issues-provider-not-shipped"
    )
    return {
        "name": "gitlab-resolution-not-shipped",
        "ok": ok,
        "detail": f"resolved={resolved} fallbackReason={reason}",
    }


def main() -> int:
    checks = [
        check_absent_from_shipped(),
        check_still_known(),
        check_live_backend_fails_closed(),
        check_resolution_reports_not_shipped(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-gitlab-demotion",
        "rid": "R7",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
