#!/usr/bin/env python3
"""Docs-only PR to default branch (PRD 026 R30 / 042 R9). Never pushes directly to trunk."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_invoke import host_verb  # noqa: E402
from host_lib import default_base_branch, remote_name, load_workflow_config  # noqa: E402


def _render_pr_body(root: Path, summary: str, test_plan: str, topic: str) -> str:
    ctx = json.dumps({"summary": summary, "test_plan": test_plan, "prd_slug": topic})
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "git_template_lib.py"), "render", "pr-body", "--context-json", ctx],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
    )
    return proc.stdout if proc.returncode == 0 else ""


def _validate_pr_body(root: Path, body: str) -> bool:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "git_template_lib.py"), "validate", "pr-body", "--body", body],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
    )
    return proc.returncode == 0


def docs_pr(root: Path, topic: str, *, dry_run: bool = False) -> dict:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "worktree_lib.py"), "docs-branch", topic],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(root),
    )
    branch = proc.stdout.strip()
    default = default_base_branch(root)
    if branch == default:
        return {"verdict": "fail", "error": "refused: cannot PR docs branch that equals trunk"}
    if dry_run:
        return {"verdict": "pass", "action": "docs-pr", "dry_run": True, "head": branch, "base": default}
    check = subprocess.run(["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    if check.returncode != 0:
        return {"verdict": "fail", "error": f"docs branch not found: {branch}"}
    summary = f"Documentation: {topic}"
    test_plan = "- [ ] Review doc-only diff\n- [ ] feat-test-plan-doc-fixtures green"
    body = _render_pr_body(root, summary, test_plan, topic)
    if not body or not _validate_pr_body(root, body):
        return {"verdict": "fail", "error": "rendered PR body failed template validation"}
    cfg = load_workflow_config(root)
    host_remote = remote_name(cfg)
    subprocess.run(["git", "-C", str(root), "push", "-u", host_remote, branch], capture_output=True)
    subprocess.run(["git", "-C", str(root), "push", host_remote, branch], capture_output=True)
    listed = host_verb(root, "pr-list", head=branch, base=default, state="open")
    if listed.get("verdict") == "ok":
        items = listed.get("data") or []
        if items:
            number = items[0].get("number")
            viewed = host_verb(root, "pr-view", number=str(number))
            url = (viewed.get("data") or {}).get("url") or ""
            return {
                "verdict": "pass",
                "action": "docs-pr",
                "pr": str(number),
                "url": url,
                "head": branch,
                "base": default,
            }
    created = host_verb(root, "pr-create", title=f"docs: {topic}", body=body, head=branch, base=default)
    if created.get("verdict") == "ok":
        data = created.get("data") or {}
        return {
            "verdict": "pass",
            "action": "docs-pr",
            "pr": str(data.get("number") or ""),
            "url": data.get("url") or "",
            "head": branch,
            "base": default,
        }
    return {
        "verdict": "degraded",
        "action": "docs-pr",
        "reason": created.get("reason", "host-failed"),
        "head": branch,
        "base": default,
        "note": "branch pushed; open PR manually",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Open a docs-only PR via host verbs")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    result = docs_pr(args.root.resolve(), args.topic, dry_run=args.dry_run)
    print(json.dumps(result))
    return 0 if result.get("verdict") in ("pass", "degraded") else 1


if __name__ == "__main__":
    raise SystemExit(main())
