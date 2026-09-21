#!/usr/bin/env python3
"""Authoring-guard preflight for unit-writing commands (PRD 032 R5/R6/R14)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

import authoring_guard as _authoring_guard

# PRD 366 extending-unit stance surface (phase 11 — tasks reference this path).
PRD363_COMPLETE_PARENT_UNIT_ID = _authoring_guard.PRD363_COMPLETE_PARENT_UNIT_ID
PRD366_EXTENDING_UNIT_ID = _authoring_guard.PRD366_EXTENDING_UNIT_ID
PRD366_BINDING_STANCE = _authoring_guard.PRD366_BINDING_STANCE
PRD366_REJECTED_STANCES = _authoring_guard.PRD366_REJECTED_STANCES
prd366_extending_unit_policy = _authoring_guard.prd366_extending_unit_policy
reject_prd366_stance_substitute = _authoring_guard.reject_prd366_stance_substitute
classify_prd366_mutation_path = _authoring_guard.classify_prd366_mutation_path


def git_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return SCRIPT_DIR.parent


def repo_root() -> Path:
    return git_root()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = repo_root()
    import authoring_guard
    authoring_guard.main([str(root), *args])
    return 0
    return 0


if __name__ == "__main__":
    run_module_main(main)
