"""Portable script runner via fail-closed interpreter probe (R2)."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from _sw import interpreter, proc
from _sw.cli import build_parser, run_module_main


def resolve_repo_root(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve().parent.parent.parent
    env_root = os.environ.get("SW_REPO_ROOT", "").strip()
    if env_root:
        return Path(env_root)
    return start


def run_script(script: Path, script_args: list[str]) -> int:
    result = interpreter.probe()
    completed = proc.run([*result.executable, str(script), *script_args], cwd=str(resolve_repo_root()))
    if completed.stdout:
        sys.stdout.write(completed.stdout)
    if completed.stderr:
        sys.stderr.write(completed.stderr)
    return completed.returncode


def build_run_parser() -> argparse.ArgumentParser:
    parser = build_parser(
        prog="sw-run",
        description="Run a Shipwright Python script with the probed interpreter.",
    )
    parser.add_argument("script", help="Path to a .py script")
    parser.add_argument("args", nargs=argparse.REMAINDER, help="Arguments forwarded to the script")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_run_parser()
    args = parser.parse_args(argv)
    script = Path(args.script)
    if not script.is_file():
        from _sw import logging_setup
        logging_setup.error(f"script not found: {script}")
        return 2
    forwarded = list(args.args)
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    return run_script(script.resolve(), forwarded)


if __name__ == "__main__":
    run_module_main(lambda: main())
