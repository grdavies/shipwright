#!/usr/bin/env python3
"""Terminal status integrity — provenance marker, validation, resolution (PRD 036 R13–R17)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess

from _sw import interpreter
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

VALID_STATUS_VERDICTS = frozenset({"merge-ready-green", "blocked"})
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GATE_SUBSET_KEYS = ("verdict", "coderabbitLanded", "head")
DEFAULT_REEMIT_MAX = 2
DEFAULT_TIP_QUIESCENCE_SECONDS = 60

DIFFERENTIATED_STALL_CAUSES = frozenset(
    {
        "orphan-worktree-adopt-pending",
        "merge-queue-wait",
        "external-ci-wait",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gate_subset(gate: Any) -> Any:
    if gate is None:
        return None
    if not isinstance(gate, dict):
        return "__invalid__"
    return {k: gate[k] for k in sorted(GATE_SUBSET_KEYS) if k in gate}


def ship_steps_checksum(ship_steps: Any) -> str | None:
    if ship_steps is None:
        return None
    if not isinstance(ship_steps, dict):
        return None
    canonical = json.dumps(ship_steps, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_provenance_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": status.get("verdict"),
        "phase": status.get("phase"),
        "head": status.get("head"),
        "gate": gate_subset(status.get("gate")),
        "shipStepsChecksum": ship_steps_checksum(status.get("shipSteps")),
    }


def compute_provenance_marker(status: dict[str, Any]) -> str:
    payload = canonical_provenance_payload(status)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attach_provenance_marker(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["provenanceMarker"] = compute_provenance_marker(doc)
    return doc


def validate_provenance_marker(status: dict[str, Any]) -> tuple[bool, str | None]:
    recorded = status.get("provenanceMarker")
    if not recorded or not isinstance(recorded, str):
        return False, "phase-status:missing-provenance"
    expected = compute_provenance_marker(status)
    if recorded != expected:
        return False, "phase-status:forged-provenance"
    return True, None


def is_full_head_sha(head: Any) -> bool:
    return isinstance(head, str) and bool(SHA_PATTERN.match(head))


def validate_gate_json(gate: Any) -> tuple[bool, str | None]:
    if gate is None:
        return True, None
    if not isinstance(gate, dict):
        return False, "phase-status:invalid-gate"
    try:
        json.loads(json.dumps(gate))
    except (TypeError, ValueError):
        return False, "phase-status:invalid-gate"
    return True, None


def validate_terminal_status_shape(status: dict[str, Any]) -> tuple[bool, str | None]:
    verdict = status.get("verdict")
    if verdict not in VALID_STATUS_VERDICTS:
        return False, "phase-status:invalid-verdict"
    ok, cause = validate_provenance_marker(status)
    if not ok:
        return False, cause
    if verdict == "merge-ready-green" and not is_full_head_sha(status.get("head")):
        return False, "phase-status:abbreviated-head"
    ok_gate, gate_cause = validate_gate_json(status.get("gate"))
    if not ok_gate:
        return False, gate_cause
    return True, None


def check_status_sha(status: dict[str, Any], expected_head: str) -> tuple[bool, str | None]:
    recorded = status.get("head")
    if not recorded:
        return False, "phase-status:missing-head"
    if not is_full_head_sha(str(recorded)):
        return False, "phase-status:abbreviated-head"
    if str(recorded) != expected_head:
        return False, "phase-status:stale"
    return True, None


def resolve_status_candidates(
    candidates: list[tuple[Path, dict[str, Any]]],
    expected_head: str | None = None,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Pick winner by head-SHA match then newest writtenAt — not path precedence (R14)."""
    pool: list[tuple[Path, dict[str, Any], str]] = []
    for path, status in candidates:
        if not isinstance(status, dict):
            continue
        if expected_head:
            head = status.get("head")
            if head and str(head) != expected_head:
                continue
        pool.append((path, status, str(status.get("writtenAt") or "")))
    if not pool and expected_head:
        for path, status in candidates:
            if isinstance(status, dict):
                pool.append((path, status, str(status.get("writtenAt") or "")))
    if not pool:
        return None, None
    pool.sort(key=lambda item: item[2], reverse=True)
    path, status, _ = pool[0]
    return path, status


def write_status_atomic(path: Path, doc: dict[str, Any], *, mode: int = 0o600) -> dict[str, Any]:
    stamped = attach_provenance_marker(dict(doc))
    if "writtenAt" not in stamped:
        stamped["writtenAt"] = utc_now()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(stamped, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".status-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return stamped


def merge_authorizing(gate_ec: int, gate: dict[str, Any]) -> bool:
    if gate_ec != 0 or gate.get("verdict") != "green":
        return False
    if gate.get("coderabbitLanded") is False:
        return False
    return True


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.py"
    if not script.is_file():
        script = root / "scripts" / "check-gate.py"
    probe = interpreter.probe()
    cmd = [*probe.executable, str(script)]
    if pr:
        cmd.append(str(pr))
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
    try:
        gate = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        gate = {"verdict": "blocked", "reason": proc.stderr.strip() or "invalid gate output"}
    return proc.returncode, gate


def resolve_pr_number(
    root: Path,
    state: dict[str, Any],
    phase_slug: str,
    status: dict[str, Any] | None,
    phase_branch: str | None,
) -> int | None:
    if status:
        raw = status.get("pr")
        if raw is not None and str(raw).strip() not in ("", "null", "None"):
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    try:
        from wave_phase_pr import recorded_open_pr

        recorded = recorded_open_pr(state, phase_slug)
        if recorded is not None:
            return recorded
    except ImportError:
        pass
    if not phase_branch:
        return None
    try:
        from host_invoke import host_verb
        from wave_phase_pr import canonical_pr_on_base, integration_branch

        integration = integration_branch(root)
        listed = host_verb(root, "pr-list", head=phase_branch, state="open", limit="10")
        if listed.get("verdict") != "ok":
            return None
        items = listed.get("data") or []
        if not isinstance(items, list) or not items:
            return None
        if integration:
            canonical = canonical_pr_on_base(items, integration)
            if canonical and canonical.get("number") is not None:
                return int(canonical["number"])
        first = items[0]
        if isinstance(first, dict) and first.get("number") is not None:
            return int(first["number"])
    except Exception:
        return None
    return None


def resolve_pr_head(root: Path, pr_number: int | None) -> str | None:
    if pr_number is None:
        return None
    try:
        from host_invoke import host_verb

        viewed = host_verb(root, "pr-view", number=str(pr_number))
        if viewed.get("verdict") != "ok":
            return None
        data = viewed.get("data") or {}
        head = data.get("headRefOid") or data.get("head")
        return str(head) if head else None
    except Exception:
        return None


def live_host_evidence_ok(
    root: Path,
    status: dict[str, Any],
    expected_head: str,
    pr_number: int | None,
) -> tuple[bool, dict[str, Any]]:
    """Re-verify live host evidence; embedded gate JSON is diagnostic only (R14)."""
    gate_ec, gate = run_check_gate(root, str(pr_number) if pr_number is not None else None)
    gate_head = str(gate.get("head") or "")
    evidence: dict[str, Any] = {
        "gateExitCode": gate_ec,
        "gate": gate,
        "branchHead": expected_head,
        "statusHead": status.get("head"),
        "gateHead": gate_head or None,
        "pr": pr_number,
    }
    if pr_number is not None:
        pr_head = resolve_pr_head(root, pr_number)
        evidence["prHead"] = pr_head
        if not is_full_head_sha(expected_head):
            evidence["authorized"] = False
            evidence["reason"] = "phase-status:abbreviated-head"
            return False, evidence
        if not merge_authorizing(gate_ec, gate):
            evidence["authorized"] = False
            evidence["reason"] = gate.get("reason") or "gate-not-green"
            return False, evidence
        if gate_head and gate_head != expected_head:
            evidence["authorized"] = False
            evidence["reason"] = "gate-head-mismatch"
            return False, evidence
        if pr_head and pr_head != expected_head:
            evidence["authorized"] = False
            evidence["reason"] = "pr-head-mismatch"
            return False, evidence
        if str(status.get("head") or "") != expected_head:
            evidence["authorized"] = False
            evidence["reason"] = "status-head-mismatch"
            return False, evidence
        evidence["authorized"] = True
        evidence["authPath"] = "pr"
        return True, evidence

    if status.get("verdict") != "merge-ready-green":
        evidence["authorized"] = False
        evidence["reason"] = "non-terminal-verdict"
        return False, evidence
    if str(status.get("head") or "") != expected_head:
        evidence["authorized"] = False
        evidence["reason"] = "status-head-mismatch"
        return False, evidence
    if gate_ec == 0 and gate.get("verdict") == "green" and gate_head and gate_head != expected_head:
        evidence["authorized"] = False
        evidence["reason"] = "gate-head-mismatch"
        return False, evidence
    embedded = status.get("gate")
    if embedded is not None:
        if not isinstance(embedded, dict):
            evidence["authorized"] = False
            evidence["reason"] = "phase-status:invalid-gate"
            return False, evidence
    evidence["authorized"] = True
    evidence["authPath"] = "local"
    return True, evidence


def tip_is_quiescent(gate: dict[str, Any], quiescence_seconds: int) -> bool:
    override = os.environ.get("SW_STATUS_TIP_QUIESCENCE_SECONDS", "").strip()
    if override:
        try:
            quiescence_seconds = max(0, int(override))
        except ValueError:
            pass
    mins = gate.get("minutesSinceHeadPush")
    if isinstance(mins, (int, float)):
        return float(mins) * 60.0 >= float(quiescence_seconds)
    return quiescence_seconds <= 0


def status_is_consumable_terminal(status: dict[str, Any] | None) -> bool:
    if not status:
        return False
    ok, _ = validate_terminal_status_shape(status)
    return ok


def classify_stuck_stale(
    root: Path,
    *,
    phase_slug: str,
    phase_branch: str,
    branch_head: str,
    status: dict[str, Any] | None,
    pr_number: int | None,
    quiescence_seconds: int = DEFAULT_TIP_QUIESCENCE_SECONDS,
) -> tuple[bool, dict[str, Any]]:
    """Classify stuck-stale only on SHA equality + tip quiescence (R15)."""
    detail: dict[str, Any] = {
        "phaseSlug": phase_slug,
        "branchHead": branch_head,
        "statusConsumable": status_is_consumable_terminal(status),
    }
    if status_is_consumable_terminal(status):
        detail["reason"] = "status-already-terminal"
        return False, detail

    if not is_full_head_sha(branch_head):
        detail["reason"] = "abbreviated-branch-head"
        return False, detail

    pr_head = resolve_pr_head(root, pr_number) if pr_number is not None else branch_head
    gate_ec, gate = run_check_gate(root, str(pr_number) if pr_number is not None else None)
    gate_head = str(gate.get("head") or "")
    status_head = str(status.get("head") or "") if status else ""

    detail.update(
        {
            "pr": pr_number,
            "prHead": pr_head,
            "gateHead": gate_head,
            "statusHead": status_head or None,
            "gateExitCode": gate_ec,
            "gateVerdict": gate.get("verdict"),
        }
    )

    if not merge_authorizing(gate_ec, gate):
        detail["reason"] = "live-evidence-not-green"
        return False, detail

    heads = [branch_head]
    if pr_number is not None:
        if not pr_head or not is_full_head_sha(pr_head):
            detail["reason"] = "missing-pr-head"
            return False, detail
        heads.append(pr_head)
    if not gate_head or not is_full_head_sha(gate_head):
        detail["reason"] = "missing-gate-head"
        return False, detail
    heads.append(gate_head)
    if status_head:
        if not is_full_head_sha(status_head):
            detail["reason"] = "abbreviated-status-head"
            return False, detail
        heads.append(status_head)

    if len(set(heads)) != 1:
        detail["reason"] = "head-sha-mismatch"
        return False, detail

    if not tip_is_quiescent(gate, quiescence_seconds):
        detail["reason"] = "tip-not-quiescent"
        return False, detail

    detail["reason"] = "stuck-stale"
    detail["unifiedHead"] = branch_head
    return True, detail



def is_differentiated_stall(stall_cause: str | None) -> bool:
    return bool(stall_cause and stall_cause in DIFFERENTIATED_STALL_CAUSES)


def orphan_worktree_pending(
    root: Path,
    state: dict[str, Any],
    *,
    phase_id: str,
    worktree_name: str,
) -> bool:
    """True when disk has a phase worktree path absent from phaseWorktrees (R7/R9)."""
    worktrees = state.get("phaseWorktrees") or {}
    if str(phase_id) in worktrees:
        return False
    wt_path = root / ".sw-worktrees" / worktree_name
    return wt_path.is_dir()


def classify_deliver_stall_cause(
    root: Path,
    state: dict[str, Any],
    next_action: str,
    *,
    phase_id: str | None = None,
    worktree_name: str | None = None,
) -> str | None:
    """Classify recoverable stall causes before budgetHalt (PRD 050 R9/R10)."""
    action = str(next_action or "")
    if action == "provision-phase" and phase_id and worktree_name:
        if orphan_worktree_pending(root, state, phase_id=str(phase_id), worktree_name=worktree_name):
            return "orphan-worktree-adopt-pending"
    if action in ("merge-run-next", "merge-enqueue") or state.get("mergeQueue") or state.get(
        "mergeJournal"
    ):
        return "merge-queue-wait"
    if action in ("await-in-flight", "collect-status", "dispatch-ship"):
        for meta in (state.get("phases") or {}).values():
            if not isinstance(meta, dict):
                continue
            if meta.get("status") != "in-flight":
                continue
            if meta.get("backgroundDispatchedAt"):
                return "external-ci-wait"
    return None


def stall_progress_key(
    state_signature: str,
    next_action: str,
    stall_cause: str | None,
) -> str:
    """Progress key includes stall predicate so predicate change resets noProgressStreak (R10)."""
    payload = {
        "signature": state_signature,
        "nextAction": next_action,
        "stallCause": stall_cause,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def build_status_document(
    *,
    verdict: str,
    phase: str,
    head: str | None = None,
    pr: int | None = None,
    gate: Any = None,
    cause: str | None = None,
    ship_steps: dict[str, Any] | None = None,
    ship_steps_path: str | None = None,
    written_at: str | None = None,
) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "verdict": verdict,
        "phase": phase,
        "phaseMode": True,
        "head": head,
        "pr": pr,
        "gate": gate,
        "writtenAt": written_at or utc_now(),
    }
    if ship_steps is not None:
        doc["shipSteps"] = ship_steps
    if ship_steps_path:
        doc["shipStepsPath"] = ship_steps_path
    if verdict == "blocked" and cause:
        doc["cause"] = cause
    return attach_provenance_marker(doc)


def derive_terminal_verdict_from_live_evidence(
    root: Path,
    *,
    pr_number: int | None,
    branch_head: str,
) -> tuple[str, dict[str, Any] | None, int | None]:
    gate_ec, gate = run_check_gate(root, str(pr_number) if pr_number is not None else None)
    gate_head = str(gate.get("head") or branch_head)
    if merge_authorizing(gate_ec, gate) and gate_head == branch_head:
        return "merge-ready-green", gate, pr_number
    cause = gate.get("reason") or f"gate-exit-{gate_ec}"
    return "blocked", gate, pr_number


def cmd_write(args: argparse.Namespace) -> int:
    gate_obj: Any = None
    if args.gate_json:
        gate_obj = json.loads(Path(args.gate_json).read_text(encoding="utf-8"))
    ship_steps = None
    ship_steps_path = args.ship_steps_path
    if args.ship_steps_json:
        ship_steps = json.loads(Path(args.ship_steps_json).read_text(encoding="utf-8"))
    elif ship_steps_path and Path(ship_steps_path).is_file():
        ship_steps = json.loads(Path(ship_steps_path).read_text(encoding="utf-8"))
    elif args.out:
        candidate = Path(args.out).parent / "ship-steps.json"
        if candidate.is_file():
            ship_steps_path = str(candidate)
            ship_steps = json.loads(candidate.read_text(encoding="utf-8"))
    pr_val: int | None = None
    if args.pr:
        pr_val = int(args.pr)
    doc = build_status_document(
        verdict=args.verdict,
        phase=args.phase,
        head=args.head,
        pr=pr_val,
        gate=gate_obj,
        cause=args.cause,
        ship_steps=ship_steps,
        ship_steps_path=ship_steps_path,
    )
    out_path = Path(args.out)
    stamped = write_status_atomic(out_path, doc)
    print(json.dumps(stamped, ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    status = json.loads(Path(args.path).read_text(encoding="utf-8"))
    ok, cause = validate_terminal_status_shape(status)
    payload = {"verdict": "pass" if ok else "fail", "cause": cause}
    print(json.dumps(payload, indent=2))
    return 0 if ok else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Terminal status integrity helpers")
    sub = parser.add_subparsers(dest="command", required=True)

    write_p = sub.add_parser("write", help="Build provenance-stamped status.json atomically")
    write_p.add_argument("--verdict", required=True)
    write_p.add_argument("--phase", required=True)
    write_p.add_argument("--head")
    write_p.add_argument("--pr")
    write_p.add_argument("--cause")
    write_p.add_argument("--out", required=True)
    write_p.add_argument("--gate-json")
    write_p.add_argument("--ship-steps-json")
    write_p.add_argument("--ship-steps-path")
    write_p.set_defaults(func=cmd_write)

    validate_p = sub.add_parser("validate", help="Validate terminal status shape + provenance")
    validate_p.add_argument("--path", required=True)
    validate_p.set_defaults(func=cmd_validate)

    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
