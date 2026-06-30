#!/usr/bin/env python3
"""Planning graph + maintenance reconciler entrypoint (PRD 033)."""
from __future__ import annotations
import subprocess
import sys
from pathlib import Path

from _sw.cli import build_parser, run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent


def git_root(plugin_root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        shell=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return plugin_root


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    plugin_root = SCRIPT_DIR.parent
    root = git_root(plugin_root)
    if not args or args[0] in {"-h", "--help"}:
        print(
            "usage: planning-graph.py reconcile|cycle-check|doctor|relief-check|next|posture|paths ...\n"
            "  planning-graph.py reconcile [--dry-run]\n"
            "  planning-graph.py next [--override]\n"
            "  planning-graph.py posture\n"
        )
        return 0
    cmd = args[0]
    rest = args[1:]
    py = sys.executable
    if cmd == "reconcile":
        return subprocess.run([py, str(plugin_root / "scripts/reconcile.py"), "planning-reconcile", *rest], shell=False).returncode
    if cmd in {"cycle-check", "doctor", "relief-check"}:
        return subprocess.run([py, str(plugin_root / "scripts/planning_graph.py"), str(root), cmd, *rest], shell=False).returncode
    if cmd == "next":
        return subprocess.run([py, str(plugin_root / "scripts/wave_deliver.py"), str(root), "next", *rest], shell=False).returncode
    if cmd == "posture":
        return subprocess.run([py, str(plugin_root / "scripts/planning_autonomy.py"), str(root), "posture"], shell=False).returncode
    if cmd == "paths":
        if not rest:
            rest = ["dirs"]
        return subprocess.run([py, str(plugin_root / "scripts/planning_paths.py"), str(root), *rest], shell=False).returncode
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    run_module_main(main)
