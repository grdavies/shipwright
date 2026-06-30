#!/usr/bin/env python3
"""Per-task TDD red-green gate (IM5 / U7). Consumes structured /tmp/sw-tdd.status.json."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from _sw.cli import run_module_main


def require_skip_reason_default() -> bool:
    for key in ("SW_PHASE_MODE", "SW_DELIVER_PHASE_MODE", "SW_CONDUCTOR_MODE"):
        val = os.environ.get(key, "").strip().lower()
        if val in ("1", "true", "phase", "phase-mode", "yes", "background_phase"):
            return True
    return False


def has_bound_scenario(data: dict) -> bool:
    scenario = str(data.get("testScenario") or "").strip()
    return bool(scenario) and scenario.lower() not in ("tbd", "todo", "n/a", "")


def evaluate(data: dict, *, require_skip_reason: bool) -> tuple[str, str, int]:
    if data.get("skipped"):
        reason = str(data.get("skipReason") or "").strip()
        if require_skip_reason:
            if not reason:
                return (
                    "fail",
                    "skipped without skipReason (no-silent-skip)",
                    20,
                )
            if has_bound_scenario(data):
                return (
                    "fail",
                    "skipped rejected when traceability lists testScenario",
                    20,
                )
        fallback = reason or "no test scenario"
        return ("skipped", fallback, 10)

    if data.get("testWeakened"):
        return ("fail", "test weakened to force green", 20)

    red = data.get("red") or {}
    green = data.get("green") or {}
    red_obs = bool(red.get("observed"))
    green_obs = bool(green.get("observed"))
    red_ec = red.get("exitCode")
    green_ec = green.get("exitCode")

    if not red_obs:
        return ("fail", "red phase not observed", 20)
    if red_ec == 0:
        return ("fail", "red phase passed — test was already green", 20)
    if not green_obs:
        return ("fail", "green phase not observed", 20)
    if green_ec != 0:
        return ("fail", "green phase did not pass", 20)

    return ("pass", "", 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tdd-gate")
    parser.add_argument("--status", help="Path to sw-tdd.status.json")
    parser.add_argument(
        "--require-skip-reason",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Reject silent skip / skip with bound testScenario (default on in deliver/phase mode)",
    )
    parser.add_argument("positional_status", nargs="?", help=argparse.SUPPRESS)
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    status_path = args.status or args.positional_status
    if not status_path:
        print(json.dumps({"verdict": "fail", "error": "missing --status PATH"}))
        return 2

    require = (
        require_skip_reason_default()
        if args.require_skip_reason is None
        else args.require_skip_reason
    )

    try:
        data = json.loads(Path(status_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(json.dumps({"verdict": "fail", "error": "invalid json"}))
        return 20

    verdict, reason, code = evaluate(data, require_skip_reason=require)
    payload: dict = {"verdict": verdict, "taskRef": data.get("taskRef")}
    if data.get("rid"):
        payload["rid"] = data.get("rid")
    if data.get("testScenario"):
        payload["testScenario"] = data.get("testScenario")
    if reason:
        payload["reason"] = reason
    if require:
        payload["requireSkipReason"] = True
    print(json.dumps(payload))
    return code


if __name__ == "__main__":
    run_module_main(main)
