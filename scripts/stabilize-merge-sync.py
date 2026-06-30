#!/usr/bin/env python3
"""Merge-base sync probe for /sw-stabilize — detect PR merge conflicts before check/thread harvest."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import build_parser, run_module_main
from host_lib import load_workflow_config, resolve_provider


def _repo_root(cwd: Path | None = None) -> Path:
    start = cwd or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return SCRIPT_DIR.parent


def _host_remote(root: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "host_lib.py"), "--root", str(root), "remote-name"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.stdout.strip() or remote_name(load_workflow_config(root))


def _default_base(root: Path) -> str:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        cfg_path = root / rel
        if cfg_path.is_file():
            try:
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                base = cfg.get("defaultBaseBranch")
                if isinstance(base, str) and base.strip():
                    return base.strip()
            except (OSError, ValueError, TypeError):
                pass
    return "main"


def _resolve_base_ref(root: Path, base_ref: str | None) -> str:
    if base_ref:
        return base_ref
    base = _default_base(root)
    remote = _host_remote(root)
    probe = subprocess.run(
        ["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/remotes/{remote}/{base}"],
        check=False,
    )
    if probe.returncode == 0:
        return f"{remote}/{base}"
    return base


def _host_verb(root: Path, verb: str, *args: str) -> dict:
    cmd = [sys.executable, str(SCRIPT_DIR / "host.py"), "--root", str(root), verb, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    try:
        return json.loads(proc.stdout or "{}")
    except ValueError:
        return {}


def _pr_json(root: Path, pr: str) -> dict | None:
    if pr:
        out = _host_verb(root, "pr-view", "--number", pr)
    else:
        resolve = _host_verb(root, "resolve-pr-for-branch")
        items = resolve.get("data") or []
        num = ""
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict):
                num = str(first.get("number") or "")
        if not num:
            return None
        out = _host_verb(root, "pr-view", "--number", num)
    if out.get("verdict") != "ok":
        return None
    data = out.get("data")
    return data if isinstance(data, dict) else None


def _list_conflict_files(root: Path, base_ref: str | None) -> list[str]:
    resolved = _resolve_base_ref(root, base_ref)
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    if head.returncode != 0:
        return []
    head_ref = head.stdout.strip()
    merge_base = subprocess.run(
        ["git", "-C", str(root), "merge-base", head_ref, resolved],
        capture_output=True,
        text=True,
        check=False,
    )
    base_oid = merge_base.stdout.strip() if merge_base.returncode == 0 else ""
    if not base_oid:
        return []
    merge_tree = subprocess.run(
        ["git", "-C", str(root), "merge-tree", base_oid, head_ref, resolved],
        capture_output=True,
        text=True,
        check=False,
    )
    text = merge_tree.stdout or ""
    paths: list[str] = []
    for line in text.splitlines():
        match = re.match(r"^  base\s+\d+\s+[0-9a-f]+\s+(.+)$", line)
        if not match:
            continue
        path = match.group(1).strip()
        if path and path not in paths:
            paths.append(path)
    return paths


def _cmd_fetch_base(root: Path, base_ref: str | None) -> int:
    ref = _resolve_base_ref(root, base_ref)
    remote = _host_remote(root)
    suffix = ref[len(f"{remote}/") :] if ref.startswith(f"{remote}/") else ref
    subprocess.run(["git", "-C", str(root), "fetch", remote, suffix], check=False)
    subprocess.run(["git", "-C", str(root), "fetch", remote, ref], check=False)
    return 0


def _cmd_status(root: Path, pr: str, base_ref: str | None) -> int:
    pj = _pr_json(root, pr)
    if pj is None:
        print(json.dumps({"verdict": "fail", "reason": "no open PR or host unavailable"}))
        return 30
    mergeable = str(pj.get("mergeable") or "UNKNOWN")
    merge_state = str(pj.get("mergeStateStatus") or "UNKNOWN")
    base_name = str(pj.get("baseRefName") or "main")
    if mergeable == "CONFLICTING" or merge_state == "DIRTY":
        payload = {
            "verdict": "conflicting",
            "mergeable": mergeable,
            "mergeStateStatus": merge_state,
            "baseRefName": base_name,
            "conflictingFiles": _list_conflict_files(root, base_ref),
            "pr": {
                "number": pj.get("number"),
                "url": pj.get("url"),
                "headRefName": pj.get("headRefName"),
            },
        }
        print(json.dumps(payload))
        return 1
    payload = {
        "verdict": "mergeable",
        "mergeable": mergeable,
        "mergeStateStatus": merge_state,
        "baseRefName": base_name,
        "pr": {
            "number": pj.get("number"),
            "url": pj.get("url"),
            "headRefName": pj.get("headRefName"),
        },
    }
    print(json.dumps(payload))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(prog="stabilize-merge-sync")
    parser.add_argument("command", choices=("status", "conflict-files", "fetch-base"))
    parser.add_argument("--pr", default="")
    parser.add_argument("--base", default="")
    args = parser.parse_args(argv)

    root = _repo_root()
    os.chdir(root)

    if args.command == "fetch-base":
        return _cmd_fetch_base(root, args.base or None)
    if args.command == "conflict-files":
        print(json.dumps(_list_conflict_files(root, args.base or None)))
        return 0
    return _cmd_status(root, args.pr, args.base or None)


if __name__ == "__main__":
    run_module_main(main)
