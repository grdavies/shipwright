#!/usr/bin/env python3
"""Unified doctor ledger, journal, and projection checks (PRD 082 R34, R26–R32 scope)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config


def _git_repo(root: Path) -> bool:
    import subprocess

    return (
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


FAILURE_LEDGER_NOT_GITIGNORED = "ledger-path-not-gitignored"
FAILURE_LEDGER_CONTRACT = "refusal-ledger-contract-fail"
FAILURE_PROJECTION_DIRTY = "projection-dirty"
FAILURE_PUT_JOURNAL_INCOMPLETE = "put-journal-incomplete"
FAILURE_AUDIT_JOURNAL_CHAIN = "audit-journal-chain-invalid"


def _check(
    name: str,
    status: str,
    *,
    failure_code: str | None = None,
    remediation: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"check": name, "status": status, **extra}
    if failure_code:
        payload["failureCode"] = failure_code
    if remediation:
        payload["remediation"] = remediation
    return payload


def check_refusal_ledger(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Refusal-ledger gitignore coverage and at-rest contract."""
    if not _git_repo(root):
        return _check(
            "refusal-ledger",
            "pass",
            note="skipped-without-git-repository",
        )
    import planning_ledger_store as pls
    import planning_refusal_ledger as prl

    ledger_dir = pls.resolve_ledger_path(root, cfg)
    contract = pls.verify_ledger_path_contract(root, ledger_dir)
    if contract.get("verdict") != "ok":
        gitignore_failed = any(
            item.get("check") == "gitignore" and item.get("status") == "fail"
            for item in contract.get("checks") or []
        )
        if gitignore_failed and not ledger_dir.exists():
            return _check(
                "refusal-ledger",
                "warn",
                failure_code=FAILURE_LEDGER_NOT_GITIGNORED,
                remediation=(
                    "add the refusal-ledger path to .gitignore before the ledger is created "
                    "(for example `.cursor/sw-refusal-ledger/`)"
                ),
                path=str(ledger_dir),
                contract=contract,
            )
        code = FAILURE_LEDGER_NOT_GITIGNORED if gitignore_failed else FAILURE_LEDGER_CONTRACT
        remediation = (
            "add the refusal-ledger path to .gitignore (for example `.cursor/sw-refusal-ledger/`)"
            if code == FAILURE_LEDGER_NOT_GITIGNORED
            else "repair owner-only ledger layout via planning_refusal_ledger.py verify"
        )
        return _check(
            "refusal-ledger",
            "fail",
            failure_code=code,
            remediation=remediation,
            path=str(ledger_dir),
            contract=contract,
        )
    at_rest = prl.verify_refusal_ledger_at_rest(root, cfg)
    return _check(
        "refusal-ledger",
        "pass",
        path=str(ledger_dir),
        entryCount=at_rest.get("entryCount", 0),
        evictionEventCount=at_rest.get("evictionEventCount", 0),
    )


def check_projection_dirty(root: Path) -> dict[str, Any]:
    """Dirty projection ledger state (R28)."""
    import planning_projection_ledger as ppl

    ledger = ppl.load_projection_ledger(root)
    if ledger.get("dirty"):
        return _check(
            "projection-dirty",
            "fail",
            failure_code=FAILURE_PROJECTION_DIRTY,
            remediation=(
                "resume projection from the last-good checkpoint via "
                "`planning_projection_ledger.resume_projection_from_checkpoint` "
                "or clear dirty after reconciling drift"
            ),
            dirtyReason=ledger.get("dirtyReason"),
            checkpointGeneration=ledger.get("checkpointGeneration"),
            entryCount=len(ledger.get("entries") or {}),
        )
    return _check(
        "projection-dirty",
        "pass",
        dirty=False,
        checkpointGeneration=ledger.get("checkpointGeneration"),
        entryCount=len(ledger.get("entries") or {}),
    )


def check_put_journal_incomplete(root: Path) -> dict[str, Any] | None:
    """Incomplete chunked issue-store put journal entries (R26)."""
    try:
        import planning_store as ps
        from planning_migrate_issue_store import issue_store_effective

        cfg = ps.load_workflow_config(root)
        if not issue_store_effective(root, cfg):
            return None
        journal = ps.load_put_journal(root)
    except Exception:  # noqa: BLE001 — doctor check is advisory / fail-open
        return None
    if not journal:
        return _check("put-journal-incomplete", "pass", pendingUnits=0)
    units = sorted(
        str(entry.get("unitId") or "")
        for entry in journal.values()
        if isinstance(entry, dict) and entry.get("unitId")
    )
    return _check(
        "put-journal-incomplete",
        "fail",
        failure_code=FAILURE_PUT_JOURNAL_INCOMPLETE,
        remediation=(
            "retry `planning_store.py put` for the listed unit id(s); the store resumes "
            "against the journaled issue id instead of creating a duplicate issue"
        ),
        pendingUnits=len(units),
        unitIds=units,
    )


def check_audit_journal_chain(root: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Hash-chained authority audit journal integrity (R26)."""
    if not _git_repo(root):
        return _check(
            "authority-audit-journal-chain",
            "pass",
            note="skipped-without-git-repository",
        )
    import planning_audit_journal as paj

    finding = paj.journal_doctor_finding(root, cfg)
    if finding is None:
        verified = paj.verify_chain(root, cfg)
        return _check(
            "authority-audit-journal-chain",
            "pass",
            entryCount=verified.get("entryCount", 0),
            chainState=verified.get("chainState"),
            journalPath=verified.get("journalPath"),
        )
    return _check(
        "authority-audit-journal-chain",
        "fail",
        failure_code=FAILURE_AUDIT_JOURNAL_CHAIN,
        remediation=finding.get("remediation")
        or "repair or truncate the audit journal, then re-run verify",
        cause=finding.get("cause"),
        journalPath=finding.get("journalPath"),
    )


def run_ledger_checks(root: Path, cfg: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Run ledger/journal/projection doctor checks scoped to R26–R32."""
    cfg = cfg if cfg is not None else load_workflow_config(root)
    checks: list[dict[str, Any]] = [
        check_refusal_ledger(root, cfg),
        check_projection_dirty(root),
        check_audit_journal_chain(root, cfg),
    ]
    put_journal = check_put_journal_incomplete(root)
    if put_journal is not None:
        checks.append(put_journal)
    return checks


def aggregate_verdict(checks: list[dict[str, Any]]) -> str:
    if any(check.get("status") == "fail" for check in checks):
        return "fail"
    if any(check.get("status") == "warn" for check in checks):
        return "degraded"
    return "ok"
