#!/usr/bin/env python3
"""Region-integrity guard for planning INDEX dual-region seam (PRD 031 R24)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig
import planning_paths
from wave_state import enumerate_scoped_runs
from _sw.cli import run_module_main


def index_rel(root: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "planning_paths.py"), str(root), "dirs"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            data = json.loads(proc.stdout)
            planning = data.get("dirs", {}).get("planningDir", "docs/planning").rstrip("/")
            return f"{planning}/INDEX.md"
        except json.JSONDecodeError:
            pass
    return "docs/planning/INDEX.md"


def collect_staged_paths(root: Path, index_rel_path: str) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only", "--", index_rel_path],
        capture_output=True,
        text=True,
        check=False,
    )
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def run_guard(root: Path, index_rel_path: str, writer: str) -> int:
    index_path = root / index_rel_path
    errors: list[str] = []

    def git_show(ref: str) -> str | None:
        proc = subprocess.run(
            ["git", "-C", str(root), "show", f"{ref}:{index_rel_path}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout

    def region_changed(old: str | None, new: str, region: str) -> bool:
        if old is None:
            old_body = "\n"
        else:
            try:
                old_body = pig.parse_regions(old).__dict__[region]
            except ValueError:
                return True
        try:
            new_body = pig.parse_regions(new).__dict__[region]
        except ValueError:
            return True
        return old_body != new_body

    old_text = git_show("HEAD")
    new_text_content = index_path.read_text(encoding="utf-8") if index_path.is_file() else ""
    if not new_text_content:
        print(json.dumps({"verdict": "pass", "note": "no INDEX content"}))
        return 0

    for region in ("structural", "derived", "inFlight"):
        if not region_changed(old_text, new_text_content, region):
            continue
        allowed = {
            "structural": frozenset({"generator", "structural"}),
            "derived": frozenset({"reconciler", "derived"}),
            "inFlight": frozenset({"deliver", "inFlight"}),
        }[region]
        if writer not in allowed:
            errors.append(
                f"region {region} modified without authorized writer "
                f"(got {writer!r}, allowed {sorted(allowed)})"
            )

    try:
        inflight_body = pig.parse_regions(new_text_content).inFlight
    except ValueError as exc:
        errors.append(f"INDEX region parse failed: {exc}")
        inflight_body = ""

    def has_live_run_state() -> bool:
        runs = enumerate_scoped_runs(root)
        for run in runs:
            if run.get("verdict") == "running":
                return True
            state_path = root / str(run.get("statePath", ""))
            if not state_path.is_file():
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            phases = state.get("phases") or {}
            if any((meta or {}).get("status") == "in-flight" for meta in phases.values()):
                return True
        return False

    if has_live_run_state() and not inflight_body.strip():
        errors.append("empty inFlight region while live deliver run-state exists")

    if errors:
        print(
            json.dumps(
                {"verdict": "fail", "error": "index region integrity violation", "violations": errors},
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps({"verdict": "pass", "action": "index-region-guard"}))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="INDEX region integrity guard")
    parser.add_argument("--repo-root", type=Path, default=SCRIPT_DIR.parent)
    parser.add_argument("--staged", action="store_true", default=True)
    parser.add_argument("--ci", action="store_true")
    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    rel = index_rel(root)
    if not collect_staged_paths(root, rel):
        return 0
    writer = os.environ.get("SW_INDEX_REGION_WRITER", "")
    return run_guard(root, rel, writer)


if __name__ == "__main__":
    run_module_main(main)
