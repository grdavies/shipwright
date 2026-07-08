#!/usr/bin/env python3
"""Gap-resolution open-issue-plus-resolved-label mismatch fixture (PRD 057 R4).

Proves, using the hermetic ``SW_ISSUES_FIXTURE=1`` in-memory issue store (no
network):

1. **File-store inert** — under a non-issue-store backend
   ``gap_resolution_partial_finding`` returns ``None`` immediately (no probe).
2. **Clean issue-store — no drift** — a gap issue that is both closed and
   labeled ``sw:gap-resolved`` is not flagged.
3. **Mismatch flagged** — a gap issue left ``open`` with the resolved label
   applied (a partial ``close_gap_issue`` failure) is surfaced as a
   ``gap-resolution-partial`` drift finding naming the unit id, with a
   remediation pointing back at the shared resolver.
4. **Doctor wiring** — ``doctor()`` includes the finding in its checks and
   downgrades verdict to ``degraded`` (never ``fail`` — advisory only) when the
   mismatch is present.

No git, no live issue store required.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from issues_lib import IssuesClient  # noqa: E402
from planning_canonical import GAP_LABEL_RESOLVED, project_label, title_prefix, type_label  # noqa: E402

_PROJECT_KEY = "gap-resolution-doctor-fixture"

_CFG = {
    "planning": {
        "store": {
            "backend": "issue-store",
            "issuesProvider": "github-issues",
            "projectKey": _PROJECT_KEY,
            "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning-store"},
        }
    },
    "host": {"provider": "github"},
}


def _load_doctor():
    path = SCRIPTS / "planning-doctor.py"
    spec = importlib.util.spec_from_file_location("planning_doctor_fixture_r4", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FixtureEnv:
    """Scope ``SW_ISSUES_FIXTURE=1`` to a block (hermetic, no network)."""

    def __enter__(self) -> "_FixtureEnv":
        self._prev = os.environ.get("SW_ISSUES_FIXTURE")
        os.environ["SW_ISSUES_FIXTURE"] = "1"
        return self

    def __exit__(self, *exc: object) -> None:
        if self._prev is None:
            os.environ.pop("SW_ISSUES_FIXTURE", None)
        else:
            os.environ["SW_ISSUES_FIXTURE"] = self._prev


def _sandbox(cfg: dict) -> Path:
    root = Path(tempfile.mkdtemp(prefix="sw-gap-resolution-doctor-"))
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)
    cfg_path = root / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    return root


def check_file_store_inert() -> dict:
    doctor = _load_doctor()
    root = _sandbox({})
    finding = doctor.gap_resolution_partial_finding(root)
    ok = finding is None
    return {"name": "file-store-inert", "ok": ok, "detail": f"finding={finding}"}


def check_clean_issue_no_drift() -> dict:
    doctor = _load_doctor()
    with _FixtureEnv():
        root = _sandbox(_CFG)
        client = IssuesClient(root, "github-issues")
        rec = client.issue_create(
            title=f"{title_prefix(_PROJECT_KEY)} gap:gap-970-clean",
            body="---\ntype: gap\nunit-id: gap-970-clean\nstatus: resolved\n---\n\nfixture\n",
            labels=sorted({GAP_LABEL_RESOLVED, project_label(_PROJECT_KEY), type_label("gap")}),
            project_key=_PROJECT_KEY,
            artifact_type="gap",
            unit_id="gap-970-clean",
        )
        client.issue_update(rec.id, state="closed", if_match=rec.etag)
        finding = doctor.gap_resolution_partial_finding(root)
    ok = finding is None
    return {"name": "clean-issue-no-drift", "ok": ok, "detail": f"finding={finding}"}


def check_mismatch_flagged() -> dict:
    doctor = _load_doctor()
    with _FixtureEnv():
        root = _sandbox(_CFG)
        client = IssuesClient(root, "github-issues")
        client.issue_create(
            title=f"{title_prefix(_PROJECT_KEY)} gap:gap-971-mismatch",
            body="---\ntype: gap\nunit-id: gap-971-mismatch\nstatus: open\n---\n\nfixture\n",
            labels=sorted({GAP_LABEL_RESOLVED, project_label(_PROJECT_KEY), type_label("gap")}),
            project_key=_PROJECT_KEY,
            artifact_type="gap",
            unit_id="gap-971-mismatch",
        )
        finding = doctor.gap_resolution_partial_finding(root)
    ok = (
        isinstance(finding, dict)
        and finding.get("check") == "gap-resolution-partial"
        and finding.get("status") == "drift"
        and finding.get("unitIds") == ["gap-971-mismatch"]
        and bool(finding.get("remediation"))
    )
    return {"name": "mismatch-flagged", "ok": ok, "detail": finding}


def check_doctor_wiring_degrades_not_fails() -> dict:
    """doctor() surfaces the finding and downgrades to degraded, never fail (advisory-only)."""
    doctor = _load_doctor()
    with _FixtureEnv():
        root = _sandbox(_CFG)
        client = IssuesClient(root, "github-issues")
        client.issue_create(
            title=f"{title_prefix(_PROJECT_KEY)} gap:gap-972-mismatch",
            body="---\ntype: gap\nunit-id: gap-972-mismatch\nstatus: open\n---\n\nfixture\n",
            labels=sorted({GAP_LABEL_RESOLVED, project_label(_PROJECT_KEY), type_label("gap")}),
            project_key=_PROJECT_KEY,
            artifact_type="gap",
            unit_id="gap-972-mismatch",
        )
        with contextlib.redirect_stdout(io.StringIO()):
            out = doctor.doctor(root, sweep=False)
    checks = [c for c in out.get("checks", []) if c.get("check") == "gap-resolution-partial"]
    ok = (
        bool(checks)
        and checks[0].get("status") == "drift"
        and "gap-resolution-partial" in out.get("warnings", [])
        and out.get("verdict") == "degraded"
    )
    return {"name": "doctor-wiring-degrades-not-fails", "ok": ok, "detail": f"verdict={out.get('verdict')} checks={checks}"}


def main() -> int:
    checks = [
        check_file_store_inert(),
        check_clean_issue_no_drift(),
        check_mismatch_flagged(),
        check_doctor_wiring_degrades_not_fails(),
    ]
    failures = [c for c in checks if not c["ok"]]
    verdict = "pass" if not failures else "fail"
    report = {
        "fixture": "planning-gap-resolution-doctor",
        "rid": "R4",
        "verdict": verdict,
        "checks": checks,
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False))
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
