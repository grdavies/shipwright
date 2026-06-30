#!/usr/bin/env python3
"""Interim privacy guard — fails closed if formerly-gitignored bodies would become tracked (PRD 031 R18)."""

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

STAGING_PREFIX = ".cursor/planning-migration-staging/"


def normalize_rel(rel: str) -> str:
    if rel.startswith(STAGING_PREFIX):
        return rel[len(STAGING_PREFIX) :]
    return rel


def is_private_source(rel: str) -> bool:
    norm = Path(rel).as_posix()
    if norm.startswith("docs/brainstorms/"):
        return True
    if norm.startswith("docs/decisions/") and not norm.endswith("INDEX.md") and not norm.endswith(
        "SUPERSEDED.log"
    ):
        return True
    if norm.startswith("docs/planning/brainstorm/"):
        return True
    if norm.startswith("docs/planning/decision/") and not norm.endswith("INDEX.md"):
        return True
    return False


def collect_paths(root: Path, mode: str) -> list[str]:
    if mode == "scan-private":
        out: list[str] = []
        for prefix in ("docs/planning/brainstorm/", "docs/planning/decision/"):
            base = root / prefix
            if not base.is_dir():
                continue
            for path in base.rglob("*.md"):
                if path.name == "INDEX.md":
                    continue
                out.append(path.relative_to(root).as_posix())
        return out
    if mode == "migration-staging":
        staging = root / ".cursor/planning-migration-staging"
        if not staging.is_dir():
            return []
        return [p.relative_to(root).as_posix() for p in staging.rglob("*") if p.is_file()]
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--diff-filter=A"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def run_guard(root: Path, mode: str) -> int:
    violations: list[str] = []
    paths = collect_paths(root, mode)
    for rel in paths:
        rel = normalize_rel(rel)
        if not is_private_source(rel):
            continue
        proc = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "-q", rel],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            violations.append(rel)
    if violations:
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "error": "formerly-private body would become tracked",
                    "paths": violations,
                }
            )
        )
        return 20
    print(json.dumps({"verdict": "pass", "action": "planning-privacy-guard", "checked": len(paths)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Planning privacy guard (PRD 031 R18)")
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--staged", action="store_true", help="Check git staged adds (default)")
    mode.add_argument("--migration-staging", action="store_true")
    mode.add_argument("--scan-private", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    selected = "staged"
    if args.migration_staging:
        selected = "migration-staging"
    elif args.scan_private:
        selected = "scan-private"
    return run_guard(root, selected)


if __name__ == "__main__":
    run_module_main(main)
