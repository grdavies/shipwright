#!/usr/bin/env python3
"""Fail-closed brainstorm↔PRD frontmatter traceability gate (PRD 009 A1 — R54/R55). Usage: doc-link-check.py --path <prd-or-brainstorm> [--tier full|standard]"""
from __future__ import annotations

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


def repo_root() -> Path:
    return git_root()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    import doc_link
    doc_link.main(['check', *args])
    return 0
    return 0


if __name__ == "__main__":
    run_module_main(main)
