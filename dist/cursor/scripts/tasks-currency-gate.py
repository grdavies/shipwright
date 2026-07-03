#!/usr/bin/env python3
"""Hard-block when frozen task checkboxes diverge from durable completion ledger (R15)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def git_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return SCRIPT_DIR.parent


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    tasks_file = ""
    state_root = str(git_root())
    i = 0
    while i < len(args):
        if args[i] == "--tasks-file" and i + 1 < len(args):
            tasks_file = args[i + 1]
            i += 2
            continue
        if args[i] == "--state-root" and i + 1 < len(args):
            state_root = args[i + 1]
            i += 2
            continue
        if args[i] in ("-h", "--help"):
            print(
                "usage: tasks-currency-gate.py [--tasks-file PATH] [--state-root PATH]",
                file=sys.stderr,
            )
            return 0
        print(json.dumps({"verdict": "fail", "error": "unknown argument"}), file=sys.stderr)
        return 2

    if not tasks_file:
        state_json = Path(state_root) / ".cursor" / "sw-deliver-state.json"
        if not state_json.is_file():
            print(json.dumps({"verdict": "fail", "error": "no --tasks-file and no deliver state"}), file=sys.stderr)
            return 2
        state = json.loads(state_json.read_text(encoding="utf-8"))
        tasks_file = str(state.get("source_task_list") or "")

    if not tasks_file or not Path(tasks_file).is_file():
        print(json.dumps({"verdict": "fail", "error": "task file not found"}), file=sys.stderr)
        return 2

    cmd = [
        sys.executable,
        str(SCRIPT_DIR / "wave_state.py"),
        state_root,
        "ledger",
        "check",
        "--tasks-file",
        tasks_file,
    ]
    return subprocess.run(cmd).returncode


if __name__ == "__main__":
    run_module_main(main)
