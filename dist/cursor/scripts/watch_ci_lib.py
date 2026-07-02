#!/usr/bin/env python3
"""CI-watch helpers — degrade to local checks-gate when host CI unavailable (PRD 026 R12)."""
from __future__ import annotations

import json
import subprocess

from _sw import interpreter
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import phase_mode_active, resolve_provider


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.py"
    probe = interpreter.probe()
    cmd = [*probe.executable, str(script)]
    if pr:
        cmd.append(pr)
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
    try:
        gate = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        gate = {"verdict": "blocked", "reason": proc.stderr.strip() or "invalid gate output"}
    return proc.returncode, gate


def host_ci_watch_available(root: Path) -> bool:
    resolved = resolve_provider(root)
    return resolved.get("verdict") == "ok" and resolved.get("provider") != "none"




def poll_check_gate_settled(root: Path, pr: str | None = None) -> dict[str, Any]:
    """Poll check-gate with backoff until terminal verdict (R12 — no blocking host watch)."""
    from _sw.poll import PollTimeoutError, load_poll_config, poll_until

    cfg = load_poll_config(root)
    last_ec = 30
    last_gate: dict[str, Any] = {}

    def settled() -> bool:
        nonlocal last_ec, last_gate
        last_ec, last_gate = run_check_gate(root, pr)
        return last_gate.get("verdict") in ("green", "red", "blocked")

    try:
        poll_until(settled, root=root)
    except PollTimeoutError as exc:
        return {
            "verdict": "yellow",
            "mode": "phase-gate-poll",
            "source": last_gate.get("source", "host"),
            "gateExitCode": last_ec,
            "gate": last_gate,
            "ciWatch": False,
            "timedOut": True,
            "attempts": exc.attempts,
            "elapsedSeconds": exc.elapsed_seconds,
            "note": "Phase-mode poll exhausted — check-gate still yellow (R12)",
        }
    return {
        "verdict": last_gate.get("verdict", "blocked"),
        "mode": "phase-gate-poll",
        "source": last_gate.get("source", "host"),
        "gateExitCode": last_ec,
        "gate": last_gate,
        "ciWatch": False,
        "pr": last_gate.get("pr"),
        "note": "Phase-mode check-gate poll settled (R12)",
    }

def watch_ci(root: Path, pr: str | None = None) -> dict[str, Any]:
    if not host_ci_watch_available(root):
        gate_ec, gate = run_check_gate(root, None)
        return {
            "verdict": gate.get("verdict", "blocked"),
            "mode": "degraded-local",
            "source": "local-evidence",
            "gateExitCode": gate_ec,
            "gate": gate,
            "ciWatch": False,
            "note": "No host CI — using local checks-gate evidence (R12)",
        }
    if phase_mode_active():
        polled = poll_check_gate_settled(root, pr)
        polled["ciWatch"] = False
        return polled
    gate_ec, gate = run_check_gate(root, pr)
    return {
        "verdict": gate.get("verdict", "blocked"),
        "mode": "host-ci",
        "source": gate.get("source", "host"),
        "gateExitCode": gate_ec,
        "gate": gate,
        "ciWatch": False,
        "pr": gate.get("pr"),
        "note": "Single-shot check-gate — phase-mode uses poll_check_gate_settled (R12)",
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="CI watch with local degradation")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--pr")
    args = parser.parse_args()
    print(json.dumps(watch_ci(args.root.resolve(), args.pr), indent=2))


if __name__ == "__main__":
    main()
