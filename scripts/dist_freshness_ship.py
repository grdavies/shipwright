#!/usr/bin/env python3
"""Ship-path dist auto-regen with bounded staging (PRD 274 R10/R11/R14)."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from _sw.cli import run_module_main

from dist_freshness import CANONICAL_REGEN_COMMAND, detect_drift, format_drift_message

DIST_PREFIXES = ("dist/cursor/", "dist/claude-code/")


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dist_tree_digest(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for prefix in DIST_PREFIXES:
        base = root / prefix.rstrip("/")
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if "__pycache__" in rel or rel.endswith(".pyc"):
                continue
            out[rel] = _file_digest(path)
    return out


def _is_generated_bundle(rel: str) -> bool:
    name = Path(rel).name
    return name.endswith(".pyz") or name.endswith(".manifest.json") or name.startswith("shipwright-")


def capture_preexisting_dist_changes(root: Path) -> set[str]:
    """Return repo-relative dist paths with operator edits (excludes zipapp bundles)."""
    return {path for path in _dist_status_paths(root) if not _is_generated_bundle(path)}


def run_regen(root: Path) -> int:
    return subprocess.run(
        [sys.executable, "-m", "sw", "generate", "--all"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    ).returncode


def _dist_status_paths(root: Path) -> set[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", "dist/"],
        capture_output=True,
        text=True,
        check=False,
    )
    paths: set[str] = set()
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        rel = line[3:].strip()
        if " -> " in rel:
            rel = rel.split(" -> ", 1)[1].strip()
        if rel.startswith("dist/"):
            paths.add(rel)
    return paths


def _changed_paths(before: dict[str, str], after: dict[str, str]) -> set[str]:
    keys = set(before) | set(after)
    return {key for key in keys if before.get(key) != after.get(key)}


def stage_paths(root: Path, paths: set[str]) -> list[str]:
    staged: list[str] = []
    for rel in sorted(paths):
        proc = subprocess.run(
            ["git", "-C", str(root), "add", "--", rel],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            staged.append(rel)
    if not staged and paths:
        subprocess.run(["git", "-C", str(root), "add", "-u", "--", "dist/"], check=False)
        proc = subprocess.run(
            ["git", "-C", str(root), "diff", "--cached", "--name-only", "--", "dist/"],
            capture_output=True,
            text=True,
            check=False,
        )
        staged = [line for line in proc.stdout.splitlines() if line]
    return staged


def ship_auto_regen(root: Path, *, dry_run: bool = False) -> dict[str, object]:
    """Regen dist when drift detected; stage only this invocation's outputs."""
    drift = detect_drift(root)
    if not drift:
        return {"verdict": "pass", "action": "noop", "drift": []}

    preexisting = capture_preexisting_dist_changes(root)
    before_digest = _dist_tree_digest(root)
    if run_regen(root) != 0:
        return {
            "verdict": "fail",
            "cause": "regen-failed",
            "regenCommand": CANONICAL_REGEN_COMMAND,
            "drift": drift,
        }

    after_status = _dist_status_paths(root)
    changed = after_status - preexisting
    if not changed:
        changed = _changed_paths(before_digest, _dist_tree_digest(root))
    overlap = sorted(preexisting & after_status)
    if overlap:
        return {
            "verdict": "fail",
            "cause": "overlapping-preexisting",
            "overlap": overlap,
            "regenCommand": CANONICAL_REGEN_COMMAND,
        }

    residual = detect_drift(root)
    if residual:
        return {
            "verdict": "fail",
            "cause": "residual-drift",
            "drift": residual,
            "regenCommand": CANONICAL_REGEN_COMMAND,
            "message": format_drift_message(residual),
        }

    staged: list[str] = []
    if changed and not dry_run:
        staged = stage_paths(root, changed)

    return {
        "verdict": "pass",
        "action": "regen",
        "changed": sorted(changed),
        "staged": staged,
        "preexisting": sorted(preexisting),
        "regenCommand": CANONICAL_REGEN_COMMAND,
    }


def cmd_regen(root: Path, *, dry_run: bool) -> int:
    result = ship_auto_regen(root, dry_run=dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("verdict") == "pass" else 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ship dist auto-regen with bounded staging")
    parser.add_argument(
        "command",
        nargs="?",
        default="regen",
        choices=("regen",),
        help="regen: detect drift, regenerate, stage invocation outputs only",
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true", help="regen without git add")
    args = parser.parse_args(argv)
    root = args.root or repo_root()
    return cmd_regen(root, dry_run=bool(args.dry_run))


if __name__ == "__main__":
    run_module_main(main)
