"""Deterministic verification-gate verdict computation (IM1 / U1; plan 005)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import evidence_read as er

VERDICT_EXIT = {"verified": 0, "inconclusive": 10, "not-verified": 20}


def _status_from_verify(doc: dict[str, Any] | None) -> str:
    if not doc:
        return "missing"
    code = int(doc.get("exitCode", 1))
    status = str(doc.get("status") or ("pass" if code == 0 else "fail"))
    return "pass" if status == "pass" and code == 0 else "fail"


def _read_dimension(path: Path | None) -> tuple[dict[str, Any] | None, str]:
    if path is None:
        return None, "missing"
    if not path.is_file():
        return None, "missing"
    try:
        doc = er.safe_json_load(path)
    except (PermissionError, json.JSONDecodeError, OSError):
        return None, "invalid"
    if not isinstance(doc, dict):
        return None, "invalid"
    return doc, "ok"


def command_identities(doc: dict[str, Any]) -> set[tuple[Any, Any]]:
    cmds = doc.get("commands")
    if isinstance(cmds, list) and cmds:
        return {(c.get("name"), c.get("status")) for c in cmds if isinstance(c, dict)}
    return {(doc.get("exitCode"), doc.get("status"))}


def failing_command_names(doc: dict[str, Any]) -> set[str]:
    cmds = doc.get("commands")
    if isinstance(cmds, list) and cmds:
        return {str(c.get("name")) for c in cmds if isinstance(c, dict) and c.get("status") == "fail"}
    if _status_from_verify(doc) == "fail":
        return {"__aggregate__"}
    return set()


def gate_failing_checks(doc: dict[str, Any] | None) -> set[str]:
    if not doc:
        return set()
    if str(doc.get("verdict") or "").lower() == "red":
        return {str(x) for x in (doc.get("failingChecks") or [])}
    return set()


def gate_is_pass(doc: dict[str, Any] | None) -> bool:
    if not doc:
        return False
    return str(doc.get("verdict") or "").lower() == "green" and not gate_failing_checks(doc)


def review_dimension(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "present": False, "status": "absent"}
    if not path.is_file():
        return {"path": str(path), "present": False, "status": "absent"}
    doc, kind = _read_dimension(path)
    if kind != "ok" or doc is None:
        return {"path": str(path), "present": True, "status": "invalid"}
    return {
        "path": str(path),
        "present": True,
        "status": _status_from_verify(doc),
    }


def verify_fresh_failure(head: dict[str, Any], baseline: dict[str, Any] | None) -> bool:
    if baseline is None:
        return False
    head_fail = failing_command_names(head)
    base_fail = failing_command_names(baseline)
    if head_fail - base_fail:
        return True
    head_bad = _status_from_verify(head) == "fail"
    base_bad = _status_from_verify(baseline) == "fail"
    return head_bad and not base_bad


def verify_preexisting(head: dict[str, Any], baseline: dict[str, Any] | None) -> bool:
    if baseline is None:
        return False
    if command_identities(head) == command_identities(baseline):
        return _status_from_verify(head) == "fail"
    head_fail = failing_command_names(head)
    base_fail = failing_command_names(baseline)
    return bool(head_fail) and head_fail <= base_fail and _status_from_verify(head) == "fail"


def gate_fresh_failure(head: dict[str, Any] | None, baseline: dict[str, Any] | None) -> bool:
    if head is None or baseline is None:
        return False
    head_fail = gate_failing_checks(head)
    base_fail = gate_failing_checks(baseline)
    return bool(head_fail - base_fail) or (bool(head_fail) and gate_is_pass(baseline))


def gate_preexisting(head: dict[str, Any] | None, baseline: dict[str, Any] | None) -> bool:
    if head is None or baseline is None:
        return False
    return gate_failing_checks(head) == gate_failing_checks(baseline) and bool(gate_failing_checks(head))


def pr_context_requires_gate(pr_context: str) -> bool:
    if pr_context == "on":
        return True
    if pr_context == "off":
        return False
    if os.environ.get("GITHUB_HEAD_REF") or os.environ.get("GITHUB_EVENT_PULL_REQUEST_NUMBER"):
        return True
    if os.environ.get("CI") and os.environ.get("GITHUB_ACTIONS"):
        return True
    return False


def compute_verdict(
    *,
    verify_path: Path | None,
    gate_path: Path | None = None,
    review_path: Path | None = None,
    baseline_verify_path: Path | None = None,
    baseline_gate_path: Path | None = None,
    require_gate: bool = False,
    pr_context: str = "auto",
) -> dict[str, Any]:
    gate_required = require_gate or pr_context_requires_gate(pr_context)
    verify_doc, verify_kind = _read_dimension(verify_path)
    gate_doc, gate_kind = _read_dimension(gate_path) if gate_required or gate_path else (None, "missing")
    base_verify, base_verify_kind = _read_dimension(baseline_verify_path)
    base_gate, base_gate_kind = _read_dimension(baseline_gate_path)

    evidence: dict[str, Any] = {
        "verify": {
            "path": str(verify_path or ""),
            "present": verify_kind != "missing" and verify_path is not None and verify_path.is_file(),
            "status": "invalid" if verify_kind == "invalid" else (
                "missing" if verify_kind == "missing" else _status_from_verify(verify_doc or {})
            ),
        },
        "review": review_dimension(review_path),
        "baseline": {
            "present": bool(
                (baseline_verify_path and baseline_verify_path.is_file())
                or (baseline_gate_path and baseline_gate_path.is_file())
            )
        },
    }

    if gate_required or gate_path is not None:
        evidence["gate"] = {
            "path": str(gate_path or ""),
            "present": gate_kind != "missing" and gate_path is not None and gate_path.is_file(),
            "status": (
                "not-required" if not gate_required and gate_kind == "missing"
                else "invalid" if gate_kind == "invalid"
                else "missing" if gate_kind == "missing"
                else ("pass" if gate_is_pass(gate_doc) else "fail")
            ),
        }
    else:
        evidence["gate"] = {
            "path": str(gate_path or ""),
            "present": False,
            "status": "not-required",
        }

    if verify_kind in ("missing", "invalid"):
        return {
            "verdict": "inconclusive",
            "reason": "required verify evidence missing or invalid",
            "inconclusiveClass": "missing-required",
            "evidence": evidence,
        }

    if gate_required and evidence["gate"]["status"] in ("missing", "invalid"):
        return {
            "verdict": "inconclusive",
            "reason": "required gate evidence missing or invalid",
            "inconclusiveClass": "missing-required",
            "evidence": evidence,
        }

    if base_verify_kind == "invalid" or base_gate_kind == "invalid":
        return {
            "verdict": "inconclusive",
            "reason": "baseline evidence rejected by safe_read",
            "inconclusiveClass": "missing-required",
            "evidence": evidence,
        }

    review_status = evidence["review"]["status"]
    if review_status not in ("absent", "pass"):
        if review_status == "invalid":
            return {
                "verdict": "inconclusive",
                "reason": "review evidence invalid",
                "inconclusiveClass": "missing-required",
                "evidence": evidence,
            }

    verify_pass = _status_from_verify(verify_doc or {}) == "pass"
    gate_status = evidence["gate"]["status"]
    gate_pass = gate_status in ("pass", "not-required")
    review_pass = review_status in ("pass", "absent")

    if verify_pass and gate_pass and review_pass:
        return {
            "verdict": "verified",
            "reason": "all required evidence passing",
            "evidence": evidence,
        }

    if gate_fresh_failure(gate_doc, base_gate):
        return {
            "verdict": "not-verified",
            "reason": "fresh gate failure attributable to head",
            "evidence": evidence,
        }

    if verify_fresh_failure(verify_doc or {}, base_verify):
        return {
            "verdict": "not-verified",
            "reason": "fresh verify failure attributable to head",
            "evidence": evidence,
        }

    if not verify_pass and base_verify is None:
        return {
            "verdict": "inconclusive",
            "reason": "verify failure without baseline for attribution",
            "inconclusiveClass": "no-baseline",
            "evidence": evidence,
        }

    if gate_status == "fail" and base_gate is None:
        return {
            "verdict": "inconclusive",
            "reason": "gate failure without baseline for attribution",
            "inconclusiveClass": "no-baseline",
            "evidence": evidence,
        }

    if verify_preexisting(verify_doc or {}, base_verify) or gate_preexisting(gate_doc, base_gate):
        return {
            "verdict": "inconclusive",
            "reason": "pre-existing unchanged failure",
            "inconclusiveClass": "unattributed",
            "evidence": evidence,
        }

    if not verify_pass or gate_status == "fail":
        return {
            "verdict": "inconclusive",
            "reason": "failure present without attribution baseline",
            "inconclusiveClass": "no-baseline",
            "evidence": evidence,
        }

    return {
        "verdict": "verified",
        "reason": "all required evidence passing",
        "evidence": evidence,
    }


def exit_code_for(verdict: dict[str, Any]) -> int:
    return VERDICT_EXIT.get(str(verdict.get("verdict")), 10)


def compute_and_record(
    root: Path,
    **kwargs: Any,
) -> tuple[dict[str, Any], int]:
    verdict = compute_verdict(**kwargs)
    try:
        import failure_signature_record_lib as fsr

        fsr.maybe_record_not_verified(root, verdict)
    except Exception:
        pass
    return verdict, exit_code_for(verdict)
