#!/usr/bin/env python3
"""Durable step-level state for /sw-ship phase-mode resume (R58, PRD 022 R26/TR4)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kernel_classification import canonical_ship_chain, load_classification, normalize_step, validate_chain_order
from plan_persist import (
    LIFECYCLE_PHASE_PLAN_PENDING,
    LIFECYCLE_PHASE_PLAN_VALIDATED,
    load_phase_plan,
    persist_phase_plan,
    phase_plan_path,
    resolve_phase_run_dir,
    validate_phase_plan_document,
)
from wave_json_io import StateCorruptError, read_json, write_json
from wave_plan_validate import phase_fallback_canonical_chain


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


SHIP_CHAIN: list[str] = canonical_ship_chain(_repo_root())


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def resolve_steps_path(root: Path, phase: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    run_dir = os.environ.get("SW_RUN_DIR", "").strip()
    if run_dir:
        return Path(run_dir) / "ship-steps.json"
    return root / ".cursor" / "sw-deliver-runs" / phase / "ship-steps.json"


def resolve_plan_file(root: Path, phase: str, explicit_out: str | None) -> Path:
    if explicit_out:
        run_dir = Path(explicit_out).parent
    else:
        run_dir = resolve_phase_run_dir(phase, None)
        if not os.environ.get("SW_RUN_DIR"):
            run_dir = root / run_dir
    return phase_plan_path(run_dir)


def authoritative_chain(root: Path, phase: str, explicit_out: str | None) -> tuple[list[str], str, dict[str, Any] | None]:
    plan_path = resolve_plan_file(root, phase, explicit_out)
    try:
        plan = load_phase_plan(plan_path, absent_ok=True)
    except StateCorruptError as exc:
        fail(f"corrupt phase-step-plan: {exc}", exit_code=20, path=str(plan_path), halt="phase-plan-corrupt")
    if plan and isinstance(plan.get("steps"), list) and plan["steps"]:
        return [normalize_step(str(s)) for s in plan["steps"]], "persisted-plan", plan
    return SHIP_CHAIN, "canonical-fallback", None


def plan_index(chain: list[str], step: str) -> int:
    norm = normalize_step(step)
    if norm not in chain:
        fail(
            f"step not in authoritative plan: {step!r}",
            exit_code=20,
            halt="exec-fidelity-not-in-plan",
            valid=chain,
        )
    return chain.index(norm)


def expected_next_step(chain: list[str], last_completed: str | None) -> str | None:
    if not last_completed:
        return chain[0] if chain else None
    idx = plan_index(chain, last_completed)
    if idx + 1 >= len(chain):
        return None
    return chain[idx + 1]




def ship_chain_is_complete(root: Path, phase: str, doc: dict[str, Any] | None, *, out: str | None = None) -> bool:
    if not doc:
        return False
    chain, _, _ = authoritative_chain(root, phase, out)
    if not chain:
        return False
    last = doc.get("lastCompletedStep")
    if not last:
        return False
    norm = normalize_step(str(last))
    if expected_next_step(chain, norm) is not None:
        return False
    return norm == normalize_step(chain[-1])


def consumability_cause_for_status(root: Path, phase: str, status: dict[str, Any], *, out: str | None = None) -> str | None:
    if status.get("verdict") != "merge-ready-green":
        return None
    if isinstance(status.get("shipSteps"), dict):
        doc = status["shipSteps"]
    else:
        steps_path = status.get("shipStepsPath")
        if steps_path and Path(steps_path).is_file():
            doc = load_steps(Path(steps_path))
        else:
            doc = load_steps(resolve_steps_path(root, phase, out))
    if ship_chain_is_complete(root, phase, doc, out=out):
        return None
    return "ship-chain:incomplete"


def assert_advance_fidelity(root: Path, chain: list[str], step: str, doc: dict[str, Any]) -> None:
    norm = normalize_step(step)
    expected = expected_next_step(chain, doc.get("lastCompletedStep"))
    if expected is None:
        fail("no further steps in plan", exit_code=20, halt="exec-fidelity-complete")
    if norm != expected:
        fail(
            f"out-of-order advance: expected {expected!r}, got {norm!r}",
            exit_code=20,
            halt="exec-fidelity-out-of-order",
            expected=expected,
            received=norm,
        )
    classification = load_classification(root)
    prefix = chain[: plan_index(chain, norm) + 1]
    order_ok, reasons = validate_chain_order(prefix, classification)
    if not order_ok:
        fail(
            "kernel ordering violation at advance",
            exit_code=20,
            halt="exec-fidelity-kernel-order",
            reasons=reasons,
        )


def load_steps(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except StateCorruptError as exc:
        fail(f"corrupt ship-steps state: {exc}", exit_code=20)


def save_steps(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc["updatedAt"] = utc_now()
    write_json(path, doc)
    os.chmod(path, 0o600)


def init_silent(
    root: Path,
    phase: str,
    *,
    out: str | None = None,
    head: str | None = None,
) -> dict[str, Any]:
    """Initialize ship-steps.json without sys.exit (ship-loop drive)."""
    path = resolve_steps_path(root, phase, out)
    head_sha = head or _git_head(root)
    chain, source, plan = authoritative_chain(root, phase, out)
    doc = {
        "phase": phase,
        "currentStep": chain[0],
        "lastCompletedStep": None,
        "stepAttempts": {},
        "headAtStart": head_sha,
        "chain": chain,
        "chainSource": source,
        "phasePlanPath": str(resolve_plan_file(root, phase, out)) if plan else None,
    }
    save_steps(path, doc)
    return {
        "verdict": "pass",
        "action": "ship-steps-init",
        "path": str(path),
        "state": doc,
    }


def cmd_init(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase")
    if not phase:
        fail("--phase required")
    out = _parse_kv(args, "--out")
    head = _parse_kv(args, "--head")
    payload = init_silent(root, phase, out=out, head=head)
    emit(payload)


def cmd_get(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    chain, source, plan = authoritative_chain(root, phase, out)
    emit(
        {
            "verdict": "pass",
            "present": bool(doc),
            "path": str(path),
            "state": doc or None,
            "authoritativeChain": chain,
            "chainSource": source,
            "phasePlan": plan,
        }
    )


def cmd_attempt(root: Path, args: list[str]) -> None:
    step = _parse_kv(args, "--step")
    if not step:
        fail("--step required")
    norm = normalize_step(step)
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    if not doc:
        init_silent(root, phase, out=str(path) if out else None)
        doc = load_steps(path)
    chain, _, _ = authoritative_chain(root, phase, out)
    plan_index(chain, norm)
    _execute_verify_gate(root, phase, out, norm)
    current = doc.get("currentStep")
    if current and normalize_step(str(current)) != norm:
        fail(
            f"attempt on non-current step: current={current!r}, attempted={norm!r}",
            exit_code=20,
            halt="exec-fidelity-wrong-step",
        )
    attempts = doc.setdefault("stepAttempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
        doc["stepAttempts"] = attempts
    attempts[norm] = int(attempts.get(norm, 0)) + 1
    doc["currentStep"] = norm
    doc["chain"] = chain
    save_steps(path, doc)
    emit({"verdict": "pass", "action": "ship-steps-attempt", "step": norm, "attempts": attempts[norm]})




def _execute_verify_gate(root: Path, phase: str, out: str | None, norm: str) -> None:
    if norm != "sw-verify":
        return
    import execute_ship

    task_list = os.environ.get("SW_TASK_LIST", "").strip() or None
    phase_id = os.environ.get("SW_PHASE_ID", "").strip()
    run_dir = resolve_steps_path(root, phase, out).parent
    gate = execute_ship.ship_verify_gate_ok(
        root,
        run_dir,
        task_list=task_list,
        phase_id=phase_id,
    )
    if gate.get("verdict") == "blocked":
        fail(
            gate.get("cause") or "execute refs not terminal",
            exit_code=20,
            halt=gate.get("halt") or "execute:refs-not-terminal",
            **{k: v for k, v in gate.items() if k not in ("verdict", "halt", "cause")},
        )


def cmd_advance(root: Path, args: list[str]) -> None:
    step = _parse_kv(args, "--step")
    if not step:
        fail("--step required")
    norm = normalize_step(step)
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    if not doc:
        fail("ship-steps missing; run init first", path=str(path))
    chain, source, _ = authoritative_chain(root, phase, out)
    assert_advance_fidelity(root, chain, norm, doc)
    _execute_verify_gate(root, phase, out, norm)
    doc["lastCompletedStep"] = norm
    nxt = expected_next_step(chain, norm)
    doc["currentStep"] = nxt
    doc["chain"] = chain
    doc["chainSource"] = source
    save_steps(path, doc)
    emit(
        {
            "verdict": "pass",
            "action": "ship-steps-advance",
            "completed": norm,
            "nextStep": nxt,
        }
    )




def advance_step_silent(
    root: Path, phase: str, step: str, *, out: str | None = None
) -> dict[str, Any]:
    """Advance without sys.exit (ship-loop drive)."""
    norm = normalize_step(step)
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    if not doc:
        fail("ship-steps missing; run init first", path=str(path))
    chain, source, _ = authoritative_chain(root, phase, out)
    assert_advance_fidelity(root, chain, norm, doc)
    _execute_verify_gate(root, phase, out, norm)
    doc["lastCompletedStep"] = norm
    nxt = expected_next_step(chain, norm)
    doc["currentStep"] = nxt
    doc["chain"] = chain
    doc["chainSource"] = source
    save_steps(path, doc)
    return {
        "verdict": "pass",
        "action": "ship-steps-advance",
        "completed": norm,
        "nextStep": nxt,
    }


def record_step_attempt_silent(
    root: Path, phase: str, step: str, *, out: str | None = None
) -> dict[str, Any]:
    norm = normalize_step(step)
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    if not doc:
        init_silent(root, phase, out=out or str(path))
        doc = load_steps(path)
    chain, _, _ = authoritative_chain(root, phase, out)
    plan_index(chain, norm)
    _execute_verify_gate(root, phase, out, norm)
    current = doc.get("currentStep")
    if current and normalize_step(str(current)) != norm:
        fail(
            f"attempt on non-current step: current={current!r}, attempted={norm!r}",
            exit_code=20,
            halt="exec-fidelity-wrong-step",
        )
    attempts = doc.setdefault("stepAttempts", {})
    if not isinstance(attempts, dict):
        attempts = {}
        doc["stepAttempts"] = attempts
    attempts[norm] = int(attempts.get(norm, 0)) + 1
    doc["currentStep"] = norm
    doc["chain"] = chain
    save_steps(path, doc)
    return {
        "verdict": "pass",
        "action": "ship-steps-attempt",
        "step": norm,
        "attempts": attempts[norm],
    }


def cmd_resolve_resume(root: Path, args: list[str]) -> None:
    explicit_from = _parse_kv(args, "--from")
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    chain, source, plan = authoritative_chain(root, phase, out)

    next_step: str | None = chain[0] if chain else None
    resume_source = "chain-start"

    if explicit_from:
        norm = normalize_step(explicit_from)
        plan_index(chain, norm)
        next_step = norm
        resume_source = "cli-from"
    elif doc.get("currentStep"):
        next_step = normalize_step(str(doc["currentStep"]))
        resume_source = "persisted-current"
    elif doc.get("lastCompletedStep"):
        next_step = expected_next_step(chain, str(doc["lastCompletedStep"]))
        resume_source = "persisted-after-last"
    else:
        last_cmd = _parse_kv(args, "--last-command")
        if last_cmd:
            mapped = normalize_step(last_cmd)
            if mapped in chain:
                idx = chain.index(mapped)
                next_step = chain[idx + 1] if idx + 1 < len(chain) else None
                resume_source = "last-command"

    emit(
        {
            "verdict": "pass",
            "action": "resolve-resume",
            "nextStep": next_step,
            "source": resume_source,
            "chainSource": source,
            "path": str(path),
            "phasePlanPath": str(resolve_plan_file(root, phase, out)) if plan else None,
            "state": doc or None,
        }
    )


def cmd_validate_plan(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    plan_path = resolve_plan_file(root, phase, out)
    steps_path = resolve_steps_path(root, phase, out)
    doc = load_steps(steps_path) if steps_path.is_file() else {}

    try:
        plan = load_phase_plan(plan_path, absent_ok=False)
    except StateCorruptError as exc:
        replacement = phase_fallback_canonical_chain(root, "ship", phase)
        emit(
            {
                "verdict": "fail",
                "action": "validate-plan",
                "disposition": "replace",
                "error": str(exc),
                "replacement": replacement,
            },
            exit_code=20,
        )

    assert plan is not None
    ok, reasons, disposition = validate_phase_plan_document(root, plan)
    if not ok:
        last_completed = doc.get("lastCompletedStep")
        if last_completed and disposition == "replace":
            chain_steps = [normalize_step(str(s)) for s in plan.get("steps") or []]
            if normalize_step(str(last_completed)) not in chain_steps:
                fail(
                    "stale plan incompatible with execution progress",
                    exit_code=20,
                    halt="phase-plan-stale",
                    reasons=reasons,
                    disposition="halt",
                )
        payload: dict[str, Any] = {
            "verdict": "fail",
            "action": "validate-plan",
            "disposition": disposition,
            "reasons": reasons,
        }
        if disposition == "replace":
            payload["replacement"] = phase_fallback_canonical_chain(root, "ship", phase)
        emit(payload, exit_code=20)

    emit({"verdict": "pass", "action": "validate-plan", "path": str(plan_path), "plan": plan})


def cmd_persist_plan(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    plan_raw = _parse_kv(args, "--plan")
    if not plan_raw:
        fail("--plan <path|json> required")
    path_arg = Path(plan_raw)
    if path_arg.is_file():
        plan = json.loads(path_arg.read_text(encoding="utf-8"))
    else:
        plan = json.loads(plan_raw)
    if not isinstance(plan, dict):
        fail("plan must be a JSON object")
    out = _parse_kv(args, "--out")
    target = resolve_plan_file(root, phase, out)
    ok, reasons, _ = validate_phase_plan_document(root, plan)
    if not ok:
        fail("refusing to persist invalid phase plan", reasons=reasons, exit_code=20)
    persist_phase_plan(target, plan)
    emit(
        {
            "verdict": "pass",
            "action": "persist-plan",
            "path": str(target),
            "lifecycleHint": LIFECYCLE_PHASE_PLAN_VALIDATED,
            "plan": plan,
        }
    )


def cmd_lifecycle_phase(root: Path, args: list[str]) -> None:
    sub = args[0] if args else ""
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    plan_path = resolve_plan_file(root, phase, out)
    if sub == "pending":
        emit(
            {
                "verdict": "pass",
                "action": "lifecycle-phase-pending",
                "phase": phase,
                "status": LIFECYCLE_PHASE_PLAN_PENDING,
                "planPath": str(plan_path),
            }
        )
    if sub == "validated":
        if not plan_path.is_file():
            fail("phase plan missing; cannot mark validated", path=str(plan_path), exit_code=20)
        emit(
            {
                "verdict": "pass",
                "action": "lifecycle-phase-validated",
                "phase": phase,
                "status": LIFECYCLE_PHASE_PLAN_VALIDATED,
                "planPath": str(plan_path),
            }
        )
    fail(f"unknown lifecycle subcommand: {sub!r}")


def cmd_sync_state(root: Path, args: list[str]) -> None:
    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    out = _parse_kv(args, "--out")
    path = resolve_steps_path(root, phase, out)
    doc = load_steps(path)
    if not doc:
        emit({"verdict": "pass", "action": "sync-state", "note": "no ship-steps file"})
    phase_ship = {
        "currentStep": doc.get("currentStep"),
        "lastCompletedStep": doc.get("lastCompletedStep"),
        "stepAttempts": doc.get("stepAttempts") or {},
        "phase": doc.get("phase") or phase,
        "stepsPath": str(path),
        "phasePlanPath": str(resolve_plan_file(root, phase, out)),
        "updatedAt": doc.get("updatedAt"),
    }
    emit({"verdict": "pass", "action": "sync-state", "phaseShip": phase_ship})



def cmd_execute_fan_out(root: Path, args: list[str]) -> None:
    import subprocess

    sub = args[0] if args else ""
    rest = args[1:]
    phase = _parse_kv(rest, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    run_dir = os.environ.get("SW_RUN_DIR", "").strip()
    if sub == "stamp":
        run_dir_arg = _parse_kv(rest, "--run-dir") or run_dir
        if not run_dir_arg:
            fail("--run-dir or SW_RUN_DIR required")
        proc = subprocess.run(
            [
                sys.executable,
                str(root / "scripts" / "intra_phase_dispatch.py"),
                str(root),
                "stamp-context",
                "--run-dir",
                run_dir_arg,
                "--conductor-mode",
                "execute_fan_out",
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            fail(proc.stderr.strip() or proc.stdout.strip() or "stamp-context failed", exit_code=proc.returncode)
        emit(json.loads(proc.stdout))
    elif sub == "frontier":
        cmd = [
            sys.executable,
            str(root / "scripts" / "execute_plan.py"),
            str(root),
            "dispatch-frontier",
            "--phase-slug",
            phase,
        ]
        rd = _parse_kv(rest, "--run-dir") or run_dir
        if rd:
            cmd.extend(["--run-dir", rd])
        proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
        if proc.returncode != 0:
            fail(proc.stderr.strip() or proc.stdout.strip() or "dispatch-frontier failed", exit_code=proc.returncode)
        emit(json.loads(proc.stdout))
    elif sub == "binding":
        task_ref = _parse_kv(rest, "--task-ref")
        if not task_ref:
            fail("--task-ref required")
        cmd = [
            sys.executable,
            str(root / "scripts" / "execute_plan.py"),
            str(root),
            "dispatch-binding",
            "--task-ref",
            task_ref,
            "--phase-slug",
            phase,
        ]
        rd = _parse_kv(rest, "--run-dir") or run_dir
        if rd:
            cmd.extend(["--run-dir", rd])
        proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
        if proc.returncode != 0:
            fail(proc.stderr.strip() or proc.stdout.strip() or "dispatch-binding failed", exit_code=proc.returncode)
        emit(json.loads(proc.stdout))
    else:
        fail("execute-fan-out subcommand required: stamp|frontier|binding")

def _parse_kv(args: list[str], flag: str) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else None
    return None


def _git_head(root: Path) -> str | None:
    import subprocess

    try:
        return (
            subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True)
            .strip()
            or None
        )
    except subprocess.CalledProcessError:
        return None


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: ship_phase_steps.py <root> "
            "<init|get|attempt|advance|resolve-resume|validate-plan|persist-plan|lifecycle-phase|sync-state|execute-fan-out|execute-gate-check|adapt-phase-plan|resume-frontier> [args...]"
        )
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]

    handlers = {
        "init": cmd_init,
        "get": cmd_get,
        "attempt": cmd_attempt,
        "advance": cmd_advance,
        "resolve-resume": cmd_resolve_resume,
        "validate-plan": cmd_validate_plan,
        "persist-plan": cmd_persist_plan,
        "lifecycle-phase": cmd_lifecycle_phase,
        "sync-state": cmd_sync_state,
        "execute-fan-out": cmd_execute_fan_out,
        "execute-gate-check": lambda r, a: __import__("execute_ship").cmd_gate_check(r, a),
        "adapt-phase-plan": lambda r, a: __import__("execute_ship").cmd_adapt_phase_plan(r, a),
        "resume-frontier": lambda r, a: __import__("execute_ship").cmd_resume_frontier(r, a),
    }
    handler = handlers.get(cmd)
    if not handler:
        fail(f"unknown command: {cmd}")
    handler(root, args)


if __name__ == "__main__":
    main()
