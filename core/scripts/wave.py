#!/usr/bin/env python3
"""Wave plan + integration dispatcher (PRD 042 phase 3)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _sw import interpreter, proc
from _sw.cli import build_parser, run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
PLUGIN_ROOT = SCRIPT_DIR.parent


def repo_root() -> Path:
    completed = proc.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        cwd=str(Path.cwd()),
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return Path(completed.stdout.strip())
    return PLUGIN_ROOT


def _python(script: str, root: Path, args: list[str]) -> int:
    probe = interpreter.probe()
    script_path = SCRIPT_DIR / script
    completed = proc.run(
        [*probe.executable, str(script_path), str(root), *args],
        cwd=str(root),
    )
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def dispatch(argv: list[str]) -> int:
    root = repo_root()
    if not argv:
        return _python("wave_deliver.py", root, [])

    cmd = argv[0]
    rest = argv[1:]

    if cmd == "spec-seed":
        return _python("wave_spec_seed.py", root, ["spec-seed", *rest])
    if cmd == "deliver-loop":
        return _python("wave_deliver_loop.py", root, ["deliver-loop", *rest])
    if cmd == "watchdog":
        return _python("wave_deliver_loop.py", root, ["watchdog", *rest])
    if cmd == "ship-lease":
        return _python("wave_lock.py", root, rest)
    if cmd in ("state", "lock", "journal", "log", "ledger"):
        return _python("wave_state.py", root, argv)
    if cmd == "tasks-currency":
        return _python("tasks-currency-gate.py", root, rest)
    if cmd == "docs-currency":
        return _python("docs-currency-gate.py", root, rest)
    if cmd == "living-docs":
        return _python("wave_living_docs.py", root, rest)
    if cmd == "inflight":
        return _python("inflight_signal.py", root, rest)
    if cmd in ("compound-ship", "retrospective", "completion"):
        return _python("wave_compound.py", root, argv)
    if cmd in ("orchestrator", "forward-merge", "phase-teardown", "phase-teardown-run", "assert-entry"):
        return _python("wave_lifecycle.py", root, argv)
    if cmd == "phase":
        if rest and rest[0] == "dispatch-env":
            return _python("wave_merge.py", root, ["phase", *rest])
        return _python("wave_lifecycle.py", root, ["phase", *rest])
    if cmd == "status":
        return _python("wave_merge.py", root, ["status", *rest])
    if cmd == "report":
        if rest and rest[0] == "blockers":
            return _python("wave_failure.py", root, ["report", "blockers", *rest[1:]])
        return _python("wave_merge.py", root, ["report", *rest])
    if cmd == "merge":
        return _python("wave_merge.py", root, ["merge", *rest])
    if cmd == "bookkeeping":
        return _python("wave_bookkeeping.py", root, rest)
    if cmd == "preflight-base":
        return _python("wave_preflight.py", root, ["base-check", *rest])
    if cmd == "preflight-capability-index":
        return _python("wave_preflight.py", root, ["capability-index-check", *rest])
    if cmd == "dispatch":
        return _python("wave_preflight.py", root, ["dispatch", *rest])
    if cmd == "intra-phase":
        return _python("intra_phase_dispatch.py", root, rest)
    if cmd == "memory":
        if rest and rest[0] == "prework":
            return _python("wave_memory_prework.py", root, rest[1:])
        return _python("wave_memory.py", root, argv)
    if cmd in ("resume", "ack"):
        return _python("wave_terminal.py", root, argv)
    if cmd in ("verify", "blast-radius", "revert", "stabilize"):
        return _python("wave_failure.py", root, argv)
    if cmd == "terminal":
        if rest and rest[0] == "deny":
            return _python("wave_failure.py", root, ["terminal", *rest])
        return _python("wave_terminal.py", root, ["terminal", *rest])
    if cmd == "sizing-report":
        task_list = None
        rest_args = list(rest)
        if "--task-list" in rest_args:
            idx = rest_args.index("--task-list")
            if idx + 1 < len(rest_args):
                task_list = rest_args[idx + 1]
        if not task_list:
            sys.stderr.write("sizing-report requires --task-list <path>\n")
            return 2
        probe = interpreter.probe()
        completed = proc.run(
            [
                *probe.executable,
                str(SCRIPT_DIR / "phase_sizing.py"),
                "--root",
                str(root),
                "score",
                task_list,
            ],
            cwd=str(root),
        )
        if completed.stdout:
            sys.stdout.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        return completed.returncode
    if cmd == "plan":
        if rest and rest[0] == "validate":
            return _python("wave_plan_validate.py", root, ["validate", *rest[1:]])
        if rest and rest[0] == "benefit-report":
            return _python("wave_plan_benefit.py", root, ["benefit-report", *rest[1:]])
        return _python("wave_deliver.py", root, ["plan", *rest])
    if cmd == "execute":
        if rest and rest[0] == "integrate":
            return _python("execute_integrate.py", root, ["integrate", *rest[1:]])
        if rest and rest[0] == "blast-radius":
            return _python("execute_failure.py", root, ["blast-radius", *rest[1:]])
        if rest and rest[0] == "remediation":
            return _python("execute_failure.py", root, ["remediation", *rest[1:]])
        if rest and rest[0] == "provision-sub-branch":
            return _python("execute_plan.py", root, ["provision-sub-branch", *rest[1:]])
        if rest and rest[0] == "teardown-sub-branch":
            return _python("execute_plan.py", root, ["teardown-sub-branch", *rest[1:]])
        sys.stderr.write("execute subcommand required: integrate|blast-radius|remediation|provision-sub-branch|teardown-sub-branch\n")
        return 2
    return _python("wave_deliver.py", root, argv)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="wave", description="Wave plan + integration dispatcher.")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    forwarded = list(args.args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    return dispatch(forwarded)


if __name__ == "__main__":
    run_module_main(main)
