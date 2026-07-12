#!/usr/bin/env python3
"""Ship-loop driver — step classification, durable resume, and awaitAgent contracts (PRD 065 R1, R2, R23)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from kernel_classification import normalize_step
from gate_evidence import (
    build_evidence_record,
    digest_bytes,
    evidence_record_path,
    write_evidence_atomic,
)
from gate_manifest import gates_by_id, is_bypass_allowed, load_manifest, resolve_gate_class
from ship_gate_handlers import is_gate_handler_step, run_gate_handler
from ship_phase_steps import (
    authoritative_chain,
    cmd_advance,
    cmd_init,
    expected_next_step,
    load_steps,
    resolve_steps_path,
    ship_chain_is_complete,
)

MECHANICAL_STEPS = frozenset(
    {
        "sw-tmp-init",
        "sw-tmp-clean",
        "sw-verify",
        "verification-gate",
        "behavioral-anomaly",
        "build-chain",
        "pre-pr-smoke",
        "decision-log",
        "gap-check",
        "sw-commit",
        "sw-pr",
        "sw-watch-ci",
        "sw-ready",
        "check-gate",
        "secret-scan",
    }
)
AGENT_STEPS = frozenset({"sw-execute", "sw-review", "sw-simplify", "sw-stabilize"})
DEFAULT_AGENT_BUDGET = 2

AGENT_OUTCOME_ARTIFACTS: dict[str, str] = {
    "sw-execute": "{runDir}/execute-integrate.status.json",
    "sw-review": "{runDir}/sw-local-review-run-report.json",
    "sw-simplify": "{runDir}/sw-simplify.status.json",
    "sw-stabilize": "{runDir}/sw-stabilize.status.json",
}

BYPASS_FLAG_TO_GATE: dict[str, str] = {
    "--fast": "gap-check",
    "--skip-local": "sw-review",
    "--skip-simplify": "sw-simplify",
}
GATE_TO_STEP = {gate_id: normalize_step(gate_id) for gate_id in BYPASS_FLAG_TO_GATE.values()}



from gate_evidence import resolve_head_sha
from ship_phase_steps import advance_step_silent, record_step_attempt_silent

INTERACTIVE_RUN_DIR_TEMPLATE = ".cursor/sw-ship-runs/{phase}"


def outcome_artifact_path(step: str, run_dir: Path) -> Path:
    norm = normalize_step(step)
    template = AGENT_OUTCOME_ARTIFACTS.get(norm, "{runDir}/{step}.status.json")
    return Path(template.format(runDir=str(run_dir), step=norm))


def interactive_run_dir(root: Path, phase: str) -> Path:
    return root / INTERACTIVE_RUN_DIR_TEMPLATE.format(phase=phase)


def resolve_mode_run_dir(root: Path, phase: str) -> Path:
    if os.environ.get("SW_PHASE_MODE", "").strip() in ("1", "true", "yes"):
        return resolve_run_dir(root, phase)
    explicit = os.environ.get("SW_RUN_DIR", "").strip()
    if explicit:
        p = Path(explicit)
        return p if p.is_absolute() else root / p
    return interactive_run_dir(root, phase)


def _attach_halt_resume(root: Path, payload: dict[str, Any], phase: str) -> dict[str, Any]:
    halt_cause = str(payload.get("halt") or payload.get("cause") or "")
    if not halt_cause:
        return payload
    from halt_resume import enrich_legitimate_halt, try_load_deliver_state

    enrich_legitimate_halt(
        payload,
        root,
        try_load_deliver_state(root),
        halt_cause=halt_cause,
        phase_slug=phase,
        persist_halt_count=False,
    )
    return payload


def agent_outcome_binding_valid(
    root: Path, artifact: Path, *, head_sha: str | None = None
) -> tuple[bool, str | None]:
    if not artifact.is_file():
        return False, "agent-outcome:missing"
    try:
        doc = json.loads(artifact.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, "agent-outcome:invalid"
    if not isinstance(doc, dict):
        return False, "agent-outcome:invalid"
    head = head_sha or resolve_head_sha(root)
    artifact_head = doc.get("head") or doc.get("headSha")
    if artifact_head and str(artifact_head) != head:
        return False, "agent-outcome:head-mismatch"
    verdict = str(doc.get("verdict") or doc.get("status") or "").lower()
    if verdict in ("fail", "blocked", "red", "halt"):
        return False, f"agent-outcome:non-pass:{verdict or 'unknown'}"
    return True, None


def step_attempt_budget_exhausted(
    doc: dict[str, Any], step: str, budget: int = DEFAULT_AGENT_BUDGET
) -> bool:
    attempts = doc.get("stepAttempts") or {}
    if not isinstance(attempts, dict):
        return False
    return int(attempts.get(normalize_step(step), 0)) >= budget


def consume_agent_outcome(
    root: Path, phase: str, *, steps_path: Path | None = None
) -> dict[str, Any]:
    path = steps_path or resolve_steps_path(root, phase, None)
    doc = load_steps(path)
    if not doc:
        fail("no ship-steps.json", halt="ship-loop:no-steps")
    current = normalize_step(str(doc.get("currentStep") or ""))
    if classify_step(current) != "agent":
        return {
            "verdict": "pass",
            "action": "consume-outcome",
            "skipped": True,
            "reason": "not-agent-step",
        }
    run_dir = resolve_mode_run_dir(root, phase)
    artifact = outcome_artifact_path(current, run_dir)
    ok, cause = agent_outcome_binding_valid(root, artifact)
    if not ok:
        return {
            "verdict": "fail",
            "action": "consume-outcome",
            "cause": cause,
            "step": current,
            "artifact": str(artifact),
        }
    advance_step_silent(root, phase, current, out=str(path))
    return {
        "verdict": "pass",
        "action": "consume-outcome",
        "step": current,
        "artifact": str(artifact),
    }


def drive_tick(
    root: Path,
    phase: str,
    *,
    steps_path: Path | None = None,
    flags: set[str] | None = None,
) -> dict[str, Any]:
    """One driver tick: mechanical execution, outcome consume, or awaitAgent."""
    path = steps_path or resolve_steps_path(root, phase, None)
    ensure_initialized(root, phase, path)
    doc = load_steps(path)
    if ship_chain_is_complete(root, phase, doc, out=str(path)):
        return {
            "verdict": "pass",
            "action": "ship-loop-drive",
            "complete": True,
            "awaitAgent": False,
            "phase": phase,
        }
    current = normalize_step(str(doc.get("currentStep") or (doc.get("chain") or ["sw-tmp-init"])[0]))
    if classify_step(current) == "agent":
        run_dir = resolve_mode_run_dir(root, phase)
        artifact = outcome_artifact_path(current, run_dir)
        if artifact.is_file():
            consumed = consume_agent_outcome(root, phase, steps_path=path)
            if consumed.get("verdict") != "pass":
                if step_attempt_budget_exhausted(doc, current):
                    blocked = {
                        "verdict": "blocked",
                        "action": "ship-loop-drive",
                        "halt": "ship-loop:agent-budget-exhausted",
                        "step": current,
                        "cause": consumed.get("cause"),
                        "awaitAgent": False,
                    }
                    return _attach_halt_resume(root, blocked, phase)
                return {**consumed, "awaitAgent": False}
            return drive_tick(root, phase, steps_path=path, flags=flags)
        if step_attempt_budget_exhausted(doc, current):
            blocked = {
                "verdict": "blocked",
                "action": "ship-loop-drive",
                "halt": "ship-loop:agent-budget-exhausted",
                "step": current,
                "awaitAgent": False,
            }
            return _attach_halt_resume(root, blocked, phase)
        record_step_attempt_silent(root, phase, current, out=str(path))
        run_dir = resolve_mode_run_dir(root, phase)
        return {
            "verdict": "pass",
            "action": "ship-loop-drive",
            "complete": False,
            "awaitAgent": True,
            "phase": phase,
            "step": current,
            "classification": "agent",
            "contract": build_agent_contract(root, phase, current, run_dir),
        }
    if is_gate_handler_step(current):
        handler = execute_mechanical_step(root, phase, steps_path=path)
        if handler.get("verdict") != "pass":
            return {
                "verdict": "fail",
                "action": "ship-loop-drive",
                "step": current,
                "awaitAgent": False,
                "handler": handler,
            }
        return drive_tick(root, phase, steps_path=path, flags=flags)
    return {
        "verdict": "pass",
        "action": "ship-loop-drive",
        "complete": False,
        "awaitAgent": False,
        "phase": phase,
        "step": current,
        "classification": "mechanical",
        "note": "non-gate mechanical step deferred to agent ship chain",
    }


def drive_until_await(
    root: Path,
    phase: str,
    *,
    max_ticks: int = 64,
    steps_path: Path | None = None,
    flags: set[str] | None = None,
) -> dict[str, Any]:
    last: dict[str, Any] = {}
    for _ in range(max(1, max_ticks)):
        last = drive_tick(root, phase, steps_path=steps_path, flags=flags)
        if last.get("complete") or last.get("awaitAgent"):
            return last
        if last.get("verdict") in ("fail", "blocked"):
            return last
        if last.get("note"):
            return last
    return last or {"verdict": "fail", "error": "drive-tick-budget-exhausted"}


def cmd_drive_tick(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    flags = active_bypass_flags()
    payload = drive_tick(root, args.phase, flags=flags)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") in ("pass",) else 20


def cmd_drive(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    flags = active_bypass_flags()
    max_ticks = int(getattr(args, "max_ticks", 64) or 64)
    payload = drive_until_await(root, args.phase, max_ticks=max_ticks, flags=flags)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload.get("verdict") == "blocked":
        return 20
    if payload.get("verdict") == "fail":
        return 20
    return 0


def cmd_consume_outcome(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    payload = consume_agent_outcome(root, args.phase)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") == "pass" else 20


def parse_bypass_flags(argv: list[str] | None = None) -> set[str]:
    tokens = list(argv if argv is not None else sys.argv[1:])
    return {flag for flag in BYPASS_FLAG_TO_GATE if flag in tokens}


def bypass_flags_from_env() -> set[str]:
    raw = os.environ.get("SW_SHIP_BYPASS_FLAGS", "").strip()
    if not raw:
        return set()
    return {part.strip() for part in raw.split(",") if part.strip() in BYPASS_FLAG_TO_GATE}


def active_bypass_flags(argv: list[str] | None = None) -> set[str]:
    return parse_bypass_flags(argv) | bypass_flags_from_env()


def gate_id_for_step(step: str) -> str | None:
    norm = normalize_step(step)
    for gate_id, mapped_step in GATE_TO_STEP.items():
        if mapped_step == norm:
            return gate_id
    return None


def bypass_flag_for_gate(gate_id: str, flags: set[str]) -> str | None:
    for flag, mapped in BYPASS_FLAG_TO_GATE.items():
        if mapped == gate_id and flag in flags:
            return flag
    return None


def validate_bypass_flags(root: Path, flags: set[str]) -> None:
    for flag in sorted(flags):
        gate_id = BYPASS_FLAG_TO_GATE[flag]
        if not is_bypass_allowed(gate_id, root=root):
            fail(
                "bypass flag targets mandatory gate",
                halt="ship-loop:bypass-mandatory-denied",
                flag=flag,
                gateId=gate_id,
            )


def write_bypass_skip_record(
    root: Path,
    phase: str,
    gate_id: str,
    *,
    flag: str,
    actor: str,
    reason: str,
) -> Path:
    root = repo_root(root)
    gate = gates_by_id(load_manifest(root))[gate_id]
    evidence = gate.get("evidence") or {}
    reason_text = reason or f"bypass:{flag}"
    execution = {
        "argv": ["ship_loop.py", "bypass", flag, f"--actor={actor}", f"--reason={reason_text}"],
        "exitCode": 0,
        "stdoutDigest": digest_bytes(b""),
        "stderrDigest": digest_bytes(reason_text.encode("utf-8")),
        "duration": 0.0,
    }
    record = build_evidence_record(
        gate_id=gate_id,
        gate_class=resolve_gate_class(gate_id, root=root),
        binding_mode=str(evidence.get("bindingMode") or "head-exact"),
        evaluation_point=str(evidence.get("evaluationPoint") or "bypass"),
        verdict="skip",
        execution=execution,
        root=root,
    )
    path = evidence_record_path(root, phase, gate_id)
    write_evidence_atomic(path, record)
    return path


def drain_bypassed_steps(
    root: Path,
    phase: str,
    *,
    steps_path: Path | None = None,
    flags: set[str] | None = None,
) -> list[str]:
    """Advance past bypass-flagged optional/advisory steps with skip evidence (R10)."""
    flags = flags if flags is not None else active_bypass_flags()
    if not flags:
        return []
    validate_bypass_flags(root, flags)
    path = steps_path or resolve_steps_path(root, phase, None)
    doc = ensure_initialized(root, phase, path)
    skipped: list[str] = []
    actor = os.environ.get("SW_SHIP_BYPASS_ACTOR", "ship-loop")
    reason = os.environ.get("SW_SHIP_BYPASS_REASON", "operator bypass flag")
    import ship_phase_steps as sps

    orig_emit = sps.emit

    def _noop_emit(*_args: Any, **_kwargs: Any) -> None:
        return None

    while True:
        doc = load_steps(path)
        if not doc:
            break
        chain, _, _ = authoritative_chain(root, phase, str(path))
        current = normalize_step(str(doc.get("currentStep") or (chain[0] if chain else "")))
        gate_id = gate_id_for_step(current)
        if not gate_id or not bypass_flag_for_gate(gate_id, flags):
            break
        flag = bypass_flag_for_gate(gate_id, flags) or ""
        write_bypass_skip_record(root, phase, gate_id, flag=flag, actor=actor, reason=reason)
        sps.emit = _noop_emit
        try:
            advance_step_silent(root, phase, current, out=str(path))
        finally:
            sps.emit = orig_emit
        skipped.append(current)
        if ship_chain_is_complete(root, phase, load_steps(path), out=str(path)):
            break
    return skipped


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def repo_root(start: Path | None = None) -> Path:
    start = (start or Path.cwd()).resolve()
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return start


def resolve_run_dir(root: Path, phase: str) -> Path:
    env = os.environ.get("SW_RUN_DIR", "").strip()
    if env:
        p = Path(env)
        return p if p.is_absolute() else root / p
    return root / ".cursor" / "sw-deliver-runs" / phase


def classify_step(step: str) -> str:
    norm = normalize_step(step)
    if norm in AGENT_STEPS:
        return "agent"
    if norm in MECHANICAL_STEPS:
        return "mechanical"
    return "mechanical"


def build_agent_contract(root: Path, phase: str, step: str, run_dir: Path) -> dict[str, Any]:
    norm = normalize_step(step)
    template = AGENT_OUTCOME_ARTIFACTS.get(norm, "{runDir}/{step}.status.json")
    outcome = template.format(runDir=str(run_dir), step=norm)
    return {
        "step": norm,
        "classification": "agent",
        "inputs": {
            "phaseSlug": phase,
            "repoRoot": str(repo_root(root)),
            "runDir": str(run_dir),
            "taskList": os.environ.get("SW_TASK_LIST", ""),
            "phaseMode": os.environ.get("SW_PHASE_MODE", ""),
        },
        "expectedOutcomeArtifact": outcome,
        "attemptBudget": DEFAULT_AGENT_BUDGET,
    }


def ensure_initialized(root: Path, phase: str, steps_path: Path) -> dict[str, Any]:
    doc = load_steps(steps_path)
    if doc:
        return doc
    cmd_init(root, ["--phase", phase, "--out", str(steps_path)])
    doc = load_steps(steps_path)
    if not doc:
        fail("failed to initialize ship-steps.json", halt="ship-loop:init-failed")
    return doc


def resume_from_durable(root: Path, phase: str, *, steps_path: Path | None = None) -> dict[str, Any]:
    """Resume using durable ship-steps.json only — no chat context (R1)."""
    path = steps_path or resolve_steps_path(root, phase, None)
    doc = ensure_initialized(root, phase, path)
    chain, chain_source, plan = authoritative_chain(root, phase, str(path))
    current = normalize_step(str(doc.get("currentStep") or (chain[0] if chain else "")))
    complete = ship_chain_is_complete(root, phase, doc, out=str(path))
    payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "ship-loop-resume",
        "phase": phase,
        "path": str(path),
        "currentStep": current,
        "authoritativeChain": chain,
        "chainSource": chain_source,
        "complete": complete,
        "classification": classify_step(current) if current else None,
    }
    if plan:
        payload["phasePlanPath"] = str(path.parent / "phase-step-plan.json")
    return payload


def step_dispatch(root: Path, phase: str, *, steps_path: Path | None = None) -> dict[str, Any]:
    path = steps_path or resolve_steps_path(root, phase, None)
    doc = ensure_initialized(root, phase, path)
    chain, chain_source, _ = authoritative_chain(root, phase, str(path))
    if ship_chain_is_complete(root, phase, doc, out=str(path)):
        return {
            "verdict": "pass",
            "action": "ship-loop-run",
            "complete": True,
            "awaitAgent": False,
            "phase": phase,
            "chainSource": chain_source,
        }
    current = normalize_step(str(doc.get("currentStep") or chain[0]))
    kind = classify_step(current)
    run_dir = resolve_run_dir(root, phase)
    result: dict[str, Any] = {
        "verdict": "pass",
        "action": "ship-loop-run",
        "complete": False,
        "phase": phase,
        "step": current,
        "classification": kind,
        "chainSource": chain_source,
        "stepsPath": str(path),
    }
    if kind == "agent":
        result["awaitAgent"] = True
        result["contract"] = build_agent_contract(root, phase, current, run_dir)
    else:
        result["awaitAgent"] = False
        if is_gate_handler_step(current):
            result["isGateHandler"] = True
            result["executeMechanical"] = "gate-handler"
    return result


def execute_mechanical_step(
    root: Path,
    phase: str,
    *,
    steps_path: Path | None = None,
) -> dict[str, Any]:
    """Run mechanical gate handler for current step and advance on pass (R9)."""
    path = steps_path or resolve_steps_path(root, phase, None)
    doc = ensure_initialized(root, phase, path)
    current = normalize_step(str(doc.get("currentStep") or ""))
    if not current:
        fail("no current step", halt="ship-loop:no-current-step")
    if not is_gate_handler_step(current):
        return {
            "verdict": "pass",
            "action": "ship-loop-execute-mechanical",
            "phase": phase,
            "step": current,
            "gateHandler": False,
            "note": "step is not an R9 gate handler",
        }
    run_dir = resolve_run_dir(root, phase)
    handler = run_gate_handler(root, phase, current, run_dir)
    if handler.get("verdict") != "pass":
        fail(
            "gate handler failed",
            exit_code=20,
            halt="ship-loop:gate-handler-failed",
            gateId=current,
            handler=handler,
        )
    cmd_advance(root, ["--phase", phase, "--step", current, "--out", str(path)])
    return {
        "verdict": "pass",
        "action": "ship-loop-execute-mechanical",
        "phase": phase,
        "step": current,
        "gateHandler": True,
        "evidencePath": handler.get("evidencePath"),
        "exitCode": handler.get("exitCode"),
    }


def cmd_classify(args: argparse.Namespace) -> int:
    kind = classify_step(args.step)
    print(json.dumps({"verdict": "pass", "step": normalize_step(args.step), "classification": kind}, indent=2))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    payload = resume_from_durable(root, args.phase)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    bypass_argv: list[str] = []
    if getattr(args, "fast", False):
        bypass_argv.append("--fast")
    if getattr(args, "skip_local", False):
        bypass_argv.append("--skip-local")
    if getattr(args, "skip_simplify", False):
        bypass_argv.append("--skip-simplify")
    flags = active_bypass_flags(bypass_argv)
    skipped = drain_bypassed_steps(root, args.phase, flags=flags)
    payload = step_dispatch(root, args.phase)
    if skipped:
        payload["bypassSkipped"] = skipped
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_execute_mechanical(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    payload = execute_mechanical_step(root, args.phase)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload.get("verdict") == "pass" else 20


def cmd_advance_cli(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    path = resolve_steps_path(root, args.phase, args.out)
    cmd_advance(root, ["--phase", args.phase, "--step", args.step, "--out", str(path)])
    return 0


def cmd_chain(args: argparse.Namespace) -> int:
    root = repo_root(args.root)
    path = resolve_steps_path(root, args.phase, args.out)
    chain, chain_source, plan = authoritative_chain(root, args.phase, str(path) if args.out else None)
    print(
        json.dumps(
            {
                "verdict": "pass",
                "chain": chain,
                "chainSource": chain_source,
                "phasePlan": plan is not None,
            },
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if len(sys.argv) >= 3 and Path(sys.argv[1]).name != "ship_loop.py" and not str(sys.argv[1]).startswith("-"):
        root = Path(sys.argv[1])
        sub = sys.argv[2]
        rest = sys.argv[3:]
        ns = argparse.Namespace(root=root, phase="", step="", out="")
        for i, token in enumerate(rest):
            if token == "--phase" and i + 1 < len(rest):
                ns.phase = rest[i + 1]
            if token == "--step" and i + 1 < len(rest):
                ns.step = rest[i + 1]
            if token == "--out" and i + 1 < len(rest):
                ns.out = rest[i + 1]
        if not ns.phase:
            ns.phase = os.environ.get("SW_PHASE_SLUG", "")
        handlers = {
            "run": cmd_run,
            "resume": cmd_resume,
            "classify": cmd_classify,
            "advance": cmd_advance_cli,
            "chain": cmd_chain,
            "execute-mechanical": cmd_execute_mechanical,
            "drive-tick": cmd_drive_tick,
            "drive": cmd_drive,
            "consume-outcome": cmd_consume_outcome,
        }
        handler = handlers.get(sub)
        if not handler:
            fail(f"unknown ship-loop command: {sub}")
        return int(handler(ns))

    parser = argparse.ArgumentParser(description="Ship-loop driver")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Emit next step dispatch (awaitAgent for agent steps)")
    run_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    run_p.add_argument("--fast", action="store_true")
    run_p.add_argument("--skip-local", action="store_true")
    run_p.add_argument("--skip-simplify", action="store_true")
    run_p.set_defaults(func=cmd_run)

    resume_p = sub.add_parser("resume", help="Resume state from durable ship-steps.json")
    resume_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    resume_p.set_defaults(func=cmd_resume)

    classify_p = sub.add_parser("classify", help="Classify a chain step")
    classify_p.add_argument("--step", required=True)
    classify_p.set_defaults(func=cmd_classify)

    advance_p = sub.add_parser("advance", help="Advance with kernel-ordering enforcement")
    advance_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    advance_p.add_argument("--step", required=True)
    advance_p.add_argument("--out", default="")
    advance_p.set_defaults(func=cmd_advance_cli)

    chain_p = sub.add_parser("chain", help="Resolve authoritative chain for phase")
    chain_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    chain_p.add_argument("--out", default="")
    chain_p.set_defaults(func=cmd_chain)

    exec_p = sub.add_parser("execute-mechanical", help="Run R9 gate handler and advance")
    exec_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    exec_p.set_defaults(func=cmd_execute_mechanical)


    drive_tick_p = sub.add_parser("drive-tick", help="Single ship-loop driver tick")
    drive_tick_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    drive_tick_p.set_defaults(func=cmd_drive_tick)

    drive_p = sub.add_parser("drive", help="Drive until awaitAgent, blocked, or complete")
    drive_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    drive_p.add_argument("--max-ticks", type=int, default=64)
    drive_p.set_defaults(func=cmd_drive)

    consume_p = sub.add_parser("consume-outcome", help="Consume durable agent-step outcome")
    consume_p.add_argument("--phase", default=os.environ.get("SW_PHASE_SLUG", ""))
    consume_p.set_defaults(func=cmd_consume_outcome)

    ns = parser.parse_args(argv)
    if not getattr(ns, "phase", "") and ns.command != "classify":
        fail("--phase required")
    return int(ns.func(ns))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)

