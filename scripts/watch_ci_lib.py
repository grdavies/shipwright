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

from check_gate_lib import (
    checks_gate_halt_remediation,
    resolve_plugin_root,
    should_halt_ci_watch_without_poll,
)


def _host_auth_halt_watch_result(
    root: Path,
    gate_ec: int,
    gate: dict[str, Any],
    *,
    mode: str,
) -> dict[str, Any]:
    resolved = resolve_provider(root)
    provider = str(resolved.get("provider") or "default")
    remediation = checks_gate_halt_remediation(
        gate,
        plugin_root=resolve_plugin_root(SCRIPT_DIR),
        provider=provider,
    )
    return {
        "verdict": "blocked",
        "mode": mode,
        "source": gate.get("source", "host"),
        "gateExitCode": gate_ec,
        "gate": gate,
        "ciWatch": False,
        "haltReasonCode": gate.get("reasonCode"),
        "remediation": remediation,
        "pr": gate.get("pr"),
        "note": "host-auth-required — halt without CI poll (R10/R22)",
    }


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.py"
    probe = interpreter.probe()
    cmd = [*probe.executable, str(script)]
    if pr:
        cmd.append(pr)
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
    raw = (proc.stdout or "").strip()
    try:
        gate = json.loads(raw or "{}")
    except json.JSONDecodeError:
        err = (proc.stderr or "").strip() or raw[:500] or "invalid gate output"
        gate = {
            "verdict": "blocked",
            "reason": err,
            "reasonCode": "checks-unavailable",
            "parseError": True,
            "gateExitCode": proc.returncode,
        }
    if not isinstance(gate, dict):
        gate = {"verdict": "blocked", "reason": "non-object gate output", "parseError": True}
    # Surface empty/failed polls — do not look like "no pending checks".
    if proc.returncode not in (0, 10, 20, 30) and "reasonCode" not in gate:
        gate.setdefault("reasonCode", "checks-unavailable")
        gate.setdefault("reason", (proc.stderr or "").strip() or f"check-gate exit {proc.returncode}")
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
        if should_halt_ci_watch_without_poll(last_gate):
            return True
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
    if should_halt_ci_watch_without_poll(last_gate):
        return _host_auth_halt_watch_result(
            root, last_ec, last_gate, mode="phase-gate-poll"
        )
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
    if should_halt_ci_watch_without_poll(gate):
        return _host_auth_halt_watch_result(root, gate_ec, gate, mode="host-auth-halt")
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
