#!/usr/bin/env python3
"""Reject diffs that modify frozen artifacts. CI authority for doc-freeze integrity (R9)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main
from check_frozen_lib import freeze_artifact, is_driver_invoked


def _parse_freeze_args(args: list[str]) -> dict[str, str | bool]:
    artifact = ""
    owner = "operator"
    unit_id = ""
    driver_invoked: bool | None = None
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--artifact" and i + 1 < len(args):
            artifact = args[i + 1]
            i += 2
            continue
        if token == "--owner" and i + 1 < len(args):
            owner = args[i + 1]
            i += 2
            continue
        if token == "--unit-id" and i + 1 < len(args):
            unit_id = args[i + 1]
            i += 2
            continue
        if token == "--driver-invoked":
            driver_invoked = True
            i += 1
            continue
        if token == "--no-driver-invoked":
            driver_invoked = False
            i += 1
            continue
        print(json.dumps({"verdict": "fail", "reason": f"unknown arg: {token}"}), file=sys.stderr)
        return {"error": "unknown-arg"}
    return {
        "artifact": artifact,
        "owner": owner,
        "unit_id": unit_id,
        "driver_invoked": driver_invoked,
    }


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd().resolve()
    if args and args[0] == "freeze":
        parsed = _parse_freeze_args(args[1:])
        if parsed.get("error"):
            return 2
        artifact = str(parsed.get("artifact") or "")
        if not artifact:
            print(json.dumps({"verdict": "fail", "reason": "--artifact required"}), file=sys.stderr)
            return 2
        receipt = freeze_artifact(
            root,
            artifact,
            owner=str(parsed.get("owner") or "operator"),
            driver_invoked=parsed.get("driver_invoked"),  # type: ignore[arg-type]
            unit_id=str(parsed.get("unit_id") or "") or None,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt.get("verdict") in {"pass", "warn"} else 20

    if args and args[0] == "freeze-commit":
        artifact = ""
        driver_invoked = is_driver_invoked()
        i = 1
        while i < len(args):
            if args[i] == "--artifact" and i + 1 < len(args):
                artifact = args[i + 1]
                i += 2
            elif args[i] == "--driver-invoked":
                driver_invoked = True
                i += 1
            elif args[i] == "--no-driver-invoked":
                driver_invoked = False
                i += 1
            else:
                print(json.dumps({"verdict": "fail", "reason": "unknown arg"}), file=sys.stderr)
                return 2
        if not artifact:
            print(json.dumps({"verdict": "fail", "reason": "--artifact required"}), file=sys.stderr)
            return 2
        receipt = freeze_artifact(
            root,
            artifact,
            owner="operator",
            driver_invoked=driver_invoked,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0 if receipt.get("verdict") in {"pass", "warn"} else 20

    base = args[0] if args else None
    if not base:
        resolver = SCRIPT_DIR / "resolve-base-branch.py"
        if resolver.is_file():
            proc = subprocess.run(
                [sys.executable, str(resolver), "diff-base"],
                capture_output=True,
                text=True,
                cwd=str(root),
            )
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    data = json.loads(proc.stdout)
                    rng = str(data.get("range") or "")
                    if ".." in rng:
                        base = rng.split("..", 1)[0]
                except json.JSONDecodeError:
                    pass
    cmd = [sys.executable, str(SCRIPT_DIR / "check_frozen_scan.py")]
    if base:
        cmd.append(base)
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    run_module_main(main)
