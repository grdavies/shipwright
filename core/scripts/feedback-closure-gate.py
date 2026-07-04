#!/usr/bin/env python3
"""Feedback closure eligibility gate (IM8 / U9). Reuses verify status + optional gate JSON."""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import subprocess

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backlog", required=True)
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--verify-status", required=True)
    parser.add_argument("--gate-json", default="")
    parser.add_argument("--require-gate", action="store_true")
    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root = Path(os.environ.get("ROOT", Path.cwd()))
    list_out = subprocess.check_output(
        [
            sys.executable,
            str(root / "scripts/feedback-backlog.py"),
            "list",
            "--open-only",
            "--backlog",
            ns.backlog,
        ],
        text=True,
    )
    items = json.loads(list_out)
    match = next((i for i in items if i.get("signalId") == ns.signal_id), None)

    if not match:
        print(json.dumps({"verdict": "not-closable", "reason": "signal not open in backlog", "signalId": ns.signal_id}))
        return 20

    def verify_pass(path: str) -> str:
        p = Path(path)
        if not p.is_file():
            return "missing"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "invalid"
        ec = data.get("exitCode", data.get("overall", {}).get("exitCode", 1))
        st = data.get("status", data.get("overall", {}).get("status", "fail"))
        return "pass" if ec == 0 and st == "pass" else "fail"

    def gate_pass(path: str) -> str:
        if not path:
            return "missing"
        p = Path(path)
        if not p.is_file():
            return "missing"
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return "invalid"
        return "pass" if data.get("verdict") == "green" else "fail"

    v = verify_pass(ns.verify_status)
    if v in ("missing", "invalid"):
        print(json.dumps({"verdict": "inconclusive", "reason": "verify status missing or invalid", "signalId": ns.signal_id}))
        return 10
    if v != "pass":
        print(json.dumps({"verdict": "not-closable", "reason": "verify not passing", "signalId": ns.signal_id}))
        return 20

    if ns.require_gate:
        g = gate_pass(ns.gate_json)
        if g in ("missing", "invalid"):
            print(json.dumps({"verdict": "inconclusive", "reason": "gate json missing or invalid", "signalId": ns.signal_id}))
            return 10
        if g != "pass":
            print(json.dumps({"verdict": "not-closable", "reason": "gate not green", "signalId": ns.signal_id}))
            return 20

    print(json.dumps({
        "verdict": "closable",
        "signalId": ns.signal_id,
        "prNumber": match.get("prNumber"),
        "description": match.get("description"),
    }))
    return 0


if __name__ == "__main__":
    run_module_main(main)
