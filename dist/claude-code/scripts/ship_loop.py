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
    payload = step_dispatch(root, args.phase)
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

    ns = parser.parse_args(argv)
    if not getattr(ns, "phase", "") and ns.command != "classify":
        fail("--phase required")
    return int(ns.func(ns))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)

