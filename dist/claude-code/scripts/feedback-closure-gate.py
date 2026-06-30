#!/usr/bin/env python3
"""Feedback closure eligibility gate (IM8 / U9). Reuses verify status + optional gate JSON. """
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json, subprocess, sys
    from pathlib import Path

    root, backlog, signal_id, verify_status, gate_json, require_gate_s = sys.argv[1:7]
    require_gate = require_gate_s == "1"

    list_out = subprocess.check_output(
        [sys.executable, str(Path(root) / "scripts/feedback-backlog.py"), "list", "--open-only", "--backlog", backlog],
        text=True,
    )
    items = json.loads(list_out)
    match = next((i for i in items if i.get("signalId") == signal_id), None)

    if not match:
        print(json.dumps({"verdict": "not-closable", "reason": "signal not open in backlog", "signalId": signal_id}))
        sys.exit(20)

    def verify_pass(path):
        p = Path(path)
        if not p.is_file():
            return "missing"
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            return "invalid"
        ec = data.get("exitCode", data.get("overall", {}).get("exitCode", 1))
        st = data.get("status", data.get("overall", {}).get("status", "fail"))
        return "pass" if ec == 0 and st == "pass" else "fail"

    def gate_pass(path):
        p = Path(path)
        if not p.is_file():
            return "missing"
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            return "invalid"
        return "pass" if data.get("verdict") == "green" else "fail"

    v = verify_pass(verify_status)
    if v == "missing" or v == "invalid":
        print(json.dumps({"verdict": "inconclusive", "reason": "verify status missing or invalid", "signalId": signal_id}))
        sys.exit(10)
    if v != "pass":
        print(json.dumps({"verdict": "not-closable", "reason": "verify not passing", "signalId": signal_id}))
        sys.exit(20)

    if require_gate:
        g = gate_pass(gate_json)
        if g in ("missing", "invalid"):
            print(json.dumps({"verdict": "inconclusive", "reason": "gate json missing or invalid", "signalId": signal_id}))
            sys.exit(10)
        if g != "pass":
            print(json.dumps({"verdict": "not-closable", "reason": "gate not green", "signalId": signal_id}))
            sys.exit(20)

    print(json.dumps({
        "verdict": "closable",
        "signalId": signal_id,
        "prNumber": match.get("prNumber"),
        "description": match.get("description"),
    }))
    sys.exit(0)
    return 0


if __name__ == "__main__":
    run_module_main(main)
