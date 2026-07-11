#!/usr/bin/env python3
"""CI guard: Agent Skills spec conformance across core and dist skill trees (PRD 064 R17)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from skills_spec_guard import SKILL_TREE_PREFIXES, check_repo


def git_root(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return SCRIPT_DIR.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Agent Skills spec conformance guard")
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--tree", action="append", dest="trees")
    parser.add_argument("--skills-ref", action="store_true")
    args = parser.parse_args(argv)
    root = (args.repo_root or git_root()).resolve()
    prefixes = tuple(args.trees) if args.trees else SKILL_TREE_PREFIXES
    result = check_repo(root, tree_prefixes=prefixes, include_skills_ref=args.skills_ref)
    print(json.dumps(result, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


if __name__ == "__main__":
    run_module_main(main)
