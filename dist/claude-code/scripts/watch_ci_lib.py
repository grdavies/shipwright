#!/usr/bin/env python3
"""CI-watch helpers — degrade to local checks-gate when host CI unavailable (PRD 026 R12)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import resolve_provider


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.py"
    cmd = ["bash", str(script)]
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
    gate_ec, gate = run_check_gate(root, pr)
    return {
        "verdict": gate.get("verdict", "blocked"),
        "mode": "host-ci",
        "source": gate.get("source", "host"),
        "gateExitCode": gate_ec,
        "gate": gate,
        "ciWatch": True,
        "pr": gate.get("pr"),
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
