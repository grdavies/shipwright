#!/usr/bin/env python3
"""Docs-on-a-branch worktree provisioning (PRD 026 R28, R29)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main


def git_root() -> Path:
    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(proc.stdout.strip()) if proc.returncode == 0 else SCRIPT_DIR.parent


def load_default_branch(root: Path) -> str:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        p = root / rel
        if p.is_file():
            try:
                b = json.loads(p.read_text(encoding="utf-8")).get("defaultBaseBranch")
                if b:
                    return str(b)
            except (json.JSONDecodeError, OSError):
                pass
    return "main"


def separate_project_handoff(root: Path, topic: str) -> dict[str, Any]:
    from host_lib import load_workflow_config
    from planning_artifact_handle import issue_store_separate_project_effective
    from planning_store import resolve_store_location, store_section

    cfg = load_workflow_config(root)
    loc = resolve_store_location(root, cfg)
    store = store_section(cfg)
    project_key = store.get("projectKey", "")
    return {
        "verdict": "pass",
        "skipped": True,
        "reason": "separate-project-issue-store",
        "handoff": {
            "topic": topic,
            "issueRefsOnly": True,
            "projectKey": project_key if isinstance(project_key, str) else "",
            "storeLocation": {
                "owner": loc.get("owner"),
                "repo": loc.get("repo"),
            },
        },
        "nextSteps": {
            "authoring": "planning_store.put with unit-id handles (no code-repo docs/)",
            "deliver": "/sw-deliver run <frozen-task-list-path>",
        },
    }


def emit_separate_project_skip(
    root: Path,
    cmd: str,
    topic: str,
    *,
    dry_run: bool = False,
) -> int:
    payload = separate_project_handoff(root, topic)
    payload["action"] = cmd
    if dry_run:
        payload["dry_run"] = True
    print(json.dumps(payload))
    return 0


def run_worktree_lib(root: Path, *args: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "worktree_lib.py"), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "worktree_lib failed")
    return proc.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = ""
    topic = ""
    dry_run = False
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("provision", "resume", "status"):
            cmd = a
        elif a == "--topic" and i + 1 < len(args):
            topic = args[i + 1]
            i += 1
        elif a == "--dry-run":
            dry_run = True
        elif a in ("-h", "--help"):
            print("usage: docs_worktree {provision|resume|status} --topic <topic> [--dry-run]", file=sys.stderr)
            return 2
        else:
            print(f"unknown arg: {a}", file=sys.stderr)
            return 2
        i += 1
    if not cmd or not topic:
        print("usage: docs_worktree {provision|resume|status} --topic <topic> [--dry-run]", file=sys.stderr)
        return 2

    root = git_root()
    from host_lib import load_workflow_config
    from planning_artifact_handle import issue_store_separate_project_effective

    cfg = load_workflow_config(root)
    if issue_store_separate_project_effective(root, cfg):
        if cmd == "status":
            payload = separate_project_handoff(root, topic)
            payload["action"] = "status"
            payload["exists"] = False
            print(json.dumps(payload))
            return 0
        if cmd in ("provision", "resume"):
            return emit_separate_project_skip(root, cmd, topic, dry_run=dry_run)

    branch = run_worktree_lib(root, "docs-branch", topic)
    default = load_default_branch(root)
    wt_name = "docs-" + re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")
    wt_root = root / ".sw-worktrees"
    path = wt_root / wt_name

    if branch == default:
        print(json.dumps({"verdict": "fail", "error": "refused: docs branch equals default trunk"}), file=sys.stderr)
        return 20
    if subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "worktree_lib.py"), "validate", branch],
        cwd=str(root),
        capture_output=True,
        check=False,
    ).returncode != 0:
        print(json.dumps({"verdict": "fail", "error": f"non-conforming docs branch: {branch}"}), file=sys.stderr)
        return 12

    if cmd == "status":
        if path.is_dir():
            print(json.dumps({"verdict": "pass", "branch": branch, "path": str(path), "exists": True}))
        else:
            print(json.dumps({"verdict": "pass", "branch": branch, "exists": False}))
        return 0
    if cmd == "resume":
        if not path.is_dir():
            print(json.dumps({"verdict": "fail", "error": "docs worktree missing — run provision first", "path": str(path)}), file=sys.stderr)
            return 1
        print(json.dumps({"verdict": "pass", "action": "resume", "branch": branch, "path": str(path), "nextSteps": {"cd": str(path), "move_agent_to_root": str(path), "memoryPrework": f"python3 scripts/wave.py memory prework record --surface sw-doc --scope docs/{topic}"}}))
        return 0

    # provision
    if path.is_dir():
        print(json.dumps({"verdict": "pass", "action": "provision", "branch": branch, "path": str(path), "note": "already exists", "nextSteps": {"cd": str(path), "move_agent_to_root": str(path), "memoryPrework": f"python3 scripts/wave.py memory prework record --surface sw-doc --scope docs/{topic}"}}))
        return 0
    if dry_run:
        print(json.dumps({"verdict": "pass", "action": "provision", "dry_run": True, "branch": branch, "path": str(path)}))
        return 0
    wt_root.mkdir(parents=True, exist_ok=True)
    from host_lib import load_workflow_config, remote_name
    remote_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "host_lib.py"), "--root", str(root), "remote-name"],
        capture_output=True,
        text=True,
        check=False,
    )
    host_remote = remote_proc.stdout.strip() or remote_name(load_workflow_config(root))
    subprocess.run(["git", "-C", str(root), "fetch", host_remote, default], check=False)
    base_ref = default
    if subprocess.run(["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{default}"], check=False).returncode != 0:
        base_ref = "HEAD"
    if subprocess.run(["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], check=False).returncode == 0:
        subprocess.run(["git", "-C", str(root), "worktree", "add", str(path), branch], check=True, capture_output=True)
    else:
        subprocess.run(["git", "-C", str(root), "worktree", "add", "-b", branch, str(path), base_ref], check=True, capture_output=True)
    print(json.dumps({"verdict": "pass", "action": "provision", "branch": branch, "path": str(path), "nextSteps": {"cd": str(path), "move_agent_to_root": str(path), "memoryPrework": f"python3 scripts/wave.py memory prework record --surface sw-doc --scope docs/{topic}"}}))
    return 0


if __name__ == "__main__":
    run_module_main(main)
