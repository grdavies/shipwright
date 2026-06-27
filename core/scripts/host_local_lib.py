#!/usr/bin/env python3
"""Helpers for host_local.sh (PRD 026 Phase 3)."""
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

from host_lib import load_workflow_config


def git_head(root: Path) -> str:
    proc = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def git_branch(root: Path) -> str:
    proc = subprocess.run(["git", "-C", str(root), "branch", "--show-current"], capture_output=True, text=True, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def default_base(root: Path) -> str:
    cfg = load_workflow_config(root)
    base = cfg.get("defaultBaseBranch")
    if isinstance(base, str) and base:
        return base
    script = root / "scripts" / "resolve_base_branch.py"
    if script.is_file():
        proc = subprocess.run([sys.executable, str(script), "trunk-name"], cwd=str(root), capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return "main"


def repo_label(root: Path) -> str:
    return root.name or os.path.basename(str(root.resolve()))


def pr_view_data(root: Path, number: str = "0") -> dict:
    head = git_head(root)
    branch = git_branch(root)
    base = default_base(root)
    repo = repo_label(root)
    num = int(number) if str(number).isdigit() else 0
    return {
        "number": num,
        "url": None,
        "headRefName": branch,
        "headRefOid": head,
        "baseRefName": base,
        "state": "OPEN",
        "isDraft": False,
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "CLEAN",
        "title": f"local:{branch}",
        "body": "local-evidence PR equivalent (no remote host)",
        "localEvidence": True,
        "nameWithOwner": f"local/{repo}",
    }


def checks_default() -> dict:
    checks = [{"name": "local-evidence", "state": "SUCCESS", "conclusion": "SUCCESS", "class": "pass", "source": "local-evidence"}]
    return {"verdict": "ok", "verb": "checks", "provider": "none", "data": checks}


def checks_from_file(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    return {"verdict": "ok", "verb": "checks", "provider": "none", "data": data}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("default-base")
    sub.add_parser("repo-label")
    sub.add_parser("repo-meta")
    sub.add_parser("resolve-pr")
    sub.add_parser("checks-default")
    p_file = sub.add_parser("checks-from-file")
    p_file.add_argument("--file", type=Path, required=True)
    p_view = sub.add_parser("pr-view")
    p_view.add_argument("--number", default="0")
    p_view_verb = sub.add_parser("pr-view-verb")
    p_view_verb.add_argument("--number", default="0")
    p_list = sub.add_parser("pr-list")
    p_list.add_argument("--head", default="")
    p_head = sub.add_parser("pr-head")
    p_head.add_argument("--number", default="0")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.cmd == "default-base":
        print(default_base(root))
    elif args.cmd == "repo-label":
        print(repo_label(root))
    elif args.cmd == "repo-meta":
        print(json.dumps({"verdict": "ok", "verb": "repo-meta", "provider": "none", "data": {"nameWithOwner": f"local/{repo_label(root)}", "defaultBranch": default_base(root), "localEvidence": True}}))
    elif args.cmd == "resolve-pr":
        view = pr_view_data(root, "0")
        print(json.dumps({"verdict": "ok", "verb": "resolve-pr-for-branch", "provider": "none", "data": [{"number": view["number"], "headRefName": view["headRefName"], "headRefOid": view["headRefOid"], "localEvidence": True}]}))
    elif args.cmd == "pr-view":
        print(json.dumps(pr_view_data(root, args.number)))
    elif args.cmd == "pr-view-verb":
        print(json.dumps({"verdict": "ok", "verb": "pr-view", "provider": "none", "data": pr_view_data(root, args.number)}))
    elif args.cmd == "pr-list":
        branch = git_branch(root)
        if args.head and branch != args.head:
            print(json.dumps({"verdict": "ok", "verb": "pr-list", "provider": "none", "data": []}))
        else:
            print(json.dumps({"verdict": "ok", "verb": "pr-list", "provider": "none", "data": [pr_view_data(root, "0")]}))
    elif args.cmd == "pr-head":
        head = git_head(root)
        num = int(args.number) if str(args.number).isdigit() else 0
        print(json.dumps({"verdict": "ok", "verb": "pr-head", "provider": "none", "data": {"headRefOid": head, "number": num, "localEvidence": True}}))
    elif args.cmd == "checks-default":
        print(json.dumps(checks_default()))
    elif args.cmd == "checks-from-file":
        print(json.dumps(checks_from_file(args.file)))
    else:
        parser.error(f"unknown command: {args.cmd}")


if __name__ == "__main__":
    main()
