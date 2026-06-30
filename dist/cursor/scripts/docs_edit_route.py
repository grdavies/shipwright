#!/usr/bin/env python3
"""Two-track docs edit driver — mechanical batch vs substantive worktree+PR (PRD 035)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))


def repo_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(proc.stdout.strip()) if proc.returncode == 0 else SCRIPT_DIR.parent


def classify(root: Path, paths: list[str], index_region: str | None) -> dict:
    args = [sys.executable, str(SCRIPT_DIR / "two_track_lib.py"), str(root), "classify"]
    if paths:
        args.append("--paths")
        args.extend(paths)
    if index_region:
        args.extend(["--index-region", index_region])
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    return json.loads(proc.stdout)


def run_merge(root: Path, dry_run: bool) -> dict:
    args = [sys.executable, str(SCRIPT_DIR / "docs-merge.py"), "open"]
    if dry_run:
        args.append("--dry-run")
    proc = subprocess.run(args, cwd=str(root), capture_output=True, text=True, check=False)
    return json.loads(proc.stdout)


def run_docs_worktree(root: Path, topic: str, dry_run: bool) -> dict:
    args = [sys.executable, str(SCRIPT_DIR / "docs_worktree.py"), "provision", "--topic", topic]
    if dry_run:
        args.append("--dry-run")
    proc = subprocess.run(args, cwd=str(root), capture_output=True, text=True, check=False)
    return json.loads(proc.stdout)


def run_docs_pr(root: Path, topic: str, dry_run: bool) -> dict:
    args = [sys.executable, str(SCRIPT_DIR / "docs_pr.py"), "--topic", topic]
    if dry_run:
        args.append("--dry-run")
    proc = subprocess.run(args, cwd=str(root), capture_output=True, text=True, check=False)
    return json.loads(proc.stdout)


def cmd_route(
    root: Path,
    paths: list[str],
    index_region: str | None,
    topic: str,
    dry_run: bool,
) -> dict:
    if not paths:
        return {"verdict": "fail", "error": "paths required"}
    classify_out = classify(root, paths, index_region)
    track = classify_out["track"]
    if track == "mechanical":
        merge_out = run_merge(root, dry_run)
        return {
            "verdict": "pass",
            "track": "mechanical",
            "classify": classify_out,
            "merge": merge_out,
        }
    topic = topic or "docs-edit"
    wt_out = run_docs_worktree(root, topic, dry_run)
    pr_out = run_docs_pr(root, topic, dry_run)
    return {
        "verdict": "pass",
        "track": "substantive",
        "classify": classify_out,
        "worktree": wt_out,
        "pr": pr_out,
    }


def cmd_route_substantive(root: Path, topic: str, dry_run: bool) -> dict:
    if not topic:
        return {"verdict": "fail", "error": "topic required"}
    wt_out = run_docs_worktree(root, topic, dry_run)
    pr_out = run_docs_pr(root, topic, dry_run)
    return {"verdict": "pass", "track": "substantive", "worktree": wt_out, "pr": pr_out}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: docs-edit-route route [--path P ...] "
            "[--index-region derived|inFlight|structural] [--dry-run]",
            file=sys.stderr,
        )
        print(
            "       docs-edit-route route-substantive --topic <topic> [--dry-run]",
            file=sys.stderr,
        )
        return 2
    cmd = args[0]
    paths: list[str] = []
    topic = ""
    index_region = ""
    dry_run = False
    i = 1
    while i < len(args):
        a = args[i]
        if a == "--topic" and i + 1 < len(args):
            topic = args[i + 1]
            i += 2
        elif a == "--path" and i + 1 < len(args):
            paths.append(args[i + 1])
            i += 2
        elif a == "--index-region" and i + 1 < len(args):
            index_region = args[i + 1]
            i += 2
        elif a == "--dry-run":
            dry_run = True
            i += 1
        else:
            print(f"unknown arg: {a}", file=sys.stderr)
            return 2
    root = repo_root()
    if cmd == "route":
        result = cmd_route(root, paths, index_region or None, topic, dry_run)
        if result.get("verdict") == "fail":
            print(json.dumps(result), file=sys.stderr)
            return 2
        print(json.dumps(result))
        return 0
    if cmd == "route-substantive":
        result = cmd_route_substantive(root, topic, dry_run)
        if result.get("verdict") == "fail":
            print(json.dumps(result), file=sys.stderr)
            return 2
        print(json.dumps(result))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
