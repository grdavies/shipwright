#!/usr/bin/env python3
"""PRD 039 R12 — contract-only mutation hook (advisory; never default-blocking)."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from _sw.cli import run_module_main

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def cfg_value(config: Path | None, key: str, default: str) -> str:
    if config and config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            cur: object = data
            for part in key.strip(".").split("."):
                if isinstance(cur, dict) and part in cur:
                    cur = cur[part]
                else:
                    return default
            return str(cur) if cur is not None else default
        except json.JSONDecodeError:
            return default
    return default


def resolve_config(root: Path, explicit: Path | None) -> Path | None:
    if explicit and explicit.is_file():
        return explicit
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            return candidate
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="verify_mutation")
    parser.add_argument("--config", help="workflow.config.json path")
    parser.add_argument("--root", default=".", help="Repository root")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root = Path(args.root).resolve()
    config = resolve_config(root, Path(args.config) if args.config else None)
    enabled = cfg_value(config, "verifyMutation.enabled", "false").lower() == "true"
    provider = cfg_value(config, "verifyMutation.provider", "none")
    command = cfg_value(config, "verifyMutation.command", "")

    if not enabled or provider == "none":
        print(
            json.dumps(
                {
                    "status": "skipped",
                    "advisory": True,
                    "reason": "verifyMutation disabled",
                    "exitCode": 0,
                }
            )
        )
        return 0

    if not command.strip():
        print(
            json.dumps(
                {
                    "status": "failed",
                    "advisory": True,
                    "reason": "verifyMutation enabled but no command configured",
                    "exitCode": 10,
                }
            )
        )
        return 10

    exclude_raw = cfg_value(config, "verifyMutation.excludeList", "[]")
    try:
        exclude_list = json.loads(exclude_raw) if exclude_raw.startswith("[") else []
    except json.JSONDecodeError:
        exclude_list = []

    env = {**os.environ, "SW_VERIFY_ROOT": str(root), "SW_MUTATION_EXCLUDE": json.dumps(exclude_list)}
    proc = subprocess.run(
        shlex.split(command),
        cwd=str(root),
        capture_output=True,
        text=True,
        env=env,
    )

    surviving = proc.returncode != 0
    payload = {
        "status": "advisory_fail" if surviving else "pass",
        "advisory": True,
        "provider": provider,
        "exitCode": 10 if surviving else 0,
        "commandExitCode": proc.returncode,
        "stdout": proc.stdout[-4000:],
        "stderr": proc.stderr[-4000:],
    }
    print(json.dumps(payload))
    return 10 if surviving else 0


if __name__ == "__main__":
    run_module_main(main)
