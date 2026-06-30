#!/usr/bin/env python3
"""Mechanical docs-only batched PR + CI-gated auto-merge (PRD 035 / 042 R9)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_invoke import host_verb  # noqa: E402
from host_lib import default_base_branch, load_workflow_config, probe_branch_protection, remote_name  # noqa: E402


def _mechanical_branch(root: Path) -> str:
    cfg = load_workflow_config(root)
    docs = cfg.get("docs") if isinstance(cfg.get("docs"), dict) else {}
    two = docs.get("twoTrack") if isinstance(docs.get("twoTrack"), dict) else {}
    branch = two.get("mechanicalBranch")
    return branch if isinstance(branch, str) and branch.strip() else "docs/mechanical-maintenance"


def _current_hash(root: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "two_track_lib.py"), str(root), "content-hash"],
        capture_output=True,
        text=True,
        check=False,
    )
    return json.loads(proc.stdout).get("hash", "")


def _protection_route(root: Path) -> str:
    return probe_branch_protection(root).get("route", "pr")


def _premerge_check(root: Path) -> dict:
    diff_file = Path(tempfile.mkstemp(prefix="sw-docs-merge-", suffix=".diff")[1])
    try:
        subprocess.run(["git", "-C", str(root), "diff", "--cached"], stdout=diff_file.open("w"), check=False)
        if diff_file.stat().st_size == 0:
            subprocess.run(["git", "-C", str(root), "diff", "HEAD"], stdout=diff_file.open("w"), check=False)
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "two_track_lib.py"), str(root), "validate-mechanical-diff", "--diff-file", str(diff_file)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.stdout.strip():
            out = json.loads(proc.stdout)
            if out.get("verdict") != "pass":
                return out
        scan = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "secret-scan.py"), "stdin"],
            input=diff_file.read_text(encoding="utf-8", errors="replace"),
            capture_output=True,
            text=True,
            check=False,
        )
        if scan.returncode != 0:
            return {"verdict": "fail", "error": "secret-scan-deny"}
        return {"verdict": "pass", "action": "premerge-check"}
    finally:
        diff_file.unlink(missing_ok=True)


def cmd_premerge_check(root: Path, dry_run: bool) -> tuple[dict, int]:
    if dry_run:
        return {"verdict": "pass", "action": "premerge-check", "dry_run": True}, 0
    out = _premerge_check(root)
    return out, 0 if out.get("verdict") == "pass" else 3


def cmd_open(root: Path, dry_run: bool) -> tuple[dict, int]:
    default = default_base_branch(root)
    mech = _mechanical_branch(root)
    hash_val = _current_hash(root)
    marker = f"<!-- two-track-index-hash: {hash_val} -->"
    if dry_run:
        return {
            "verdict": "pass",
            "action": "open",
            "dry_run": True,
            "head": mech,
            "base": default,
            "hash": hash_val,
            "route": _protection_route(root),
        }, 0
    route = _protection_route(root)
    if route == "direct":
        return {"verdict": "pass", "action": "open", "route": "direct", "note": "use direct-trunk subcommand"}, 0
    if subprocess.run(["git", "-C", str(root), "show-ref", "--verify", "--quiet", f"refs/heads/{mech}"]).returncode != 0:
        subprocess.run(["git", "-C", str(root), "branch", mech, default], check=False)
        subprocess.run(["git", "-C", str(root), "checkout", "-b", mech, default], check=False)
    summary = "chore(docs): mechanical planning maintenance batch"
    test_plan = "- [ ] feat-test-plan-two-track-fixtures green"
    ctx = json.dumps({"summary": summary, "test_plan": test_plan, "prd_slug": "mechanical-maintenance"})
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "git_template_lib.py"), "render", "pr-body", "--context-json", ctx],
        capture_output=True,
        text=True,
        check=False,
    )
    body = (proc.stdout or "") + f"\n\n{marker}"
    host_remote = remote_name(load_workflow_config(root))
    subprocess.run(["git", "-C", str(root), "push", "-u", host_remote, mech], capture_output=True)
    subprocess.run(["git", "-C", str(root), "push", host_remote, mech], capture_output=True)
    listed = host_verb(root, "pr-list", head=mech, base=default, state="open")
    pr = ""
    if listed.get("verdict") == "ok" and (listed.get("data") or []):
        pr = str(listed["data"][0].get("number") or "")
    else:
        created = host_verb(
            root,
            "pr-create",
            title="docs: mechanical maintenance batch",
            body=body,
            head=mech,
            base=default,
        )
        if created.get("verdict") == "ok":
            pr = str((created.get("data") or {}).get("number") or "")
    if pr:
        return {"verdict": "pass", "action": "open", "pr": pr, "head": mech, "base": default, "hash": hash_val, "route": "pr"}, 0
    return {"verdict": "degraded", "action": "open", "reason": "host-failed", "head": mech, "base": default, "hash": hash_val}, 0


def cmd_merge_if_ready(root: Path, dry_run: bool, embedded_hash: str, pr_number: str) -> tuple[dict, int]:
    hash_at_open = embedded_hash or _current_hash(root)
    live_hash = _current_hash(root)
    if live_hash != hash_at_open:
        return {
            "verdict": "fail",
            "action": "merge-if-ready",
            "error": "content-hash-advanced",
            "openHash": hash_at_open,
            "liveHash": live_hash,
        }, 14
    if dry_run:
        return {"verdict": "pass", "action": "merge-if-ready", "dry_run": True, "hash": live_hash}, 0
    pre = _premerge_check(root)
    if pre.get("verdict") != "pass":
        return pre, 3
    default = default_base_branch(root)
    mech = _mechanical_branch(root)
    pr = pr_number
    if not pr:
        listed = host_verb(root, "pr-list", head=mech, base=default, state="open")
        if listed.get("verdict") == "ok" and (listed.get("data") or []):
            pr = str(listed["data"][0].get("number") or "")
    gate_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "check-gate.sh"), pr or ""],
        capture_output=True,
        text=True,
        check=False,
    )
    gate_out = gate_proc.stdout.strip() or "{}"
    try:
        gate = json.loads(gate_out)
    except json.JSONDecodeError:
        gate = {"verdict": "blocked"}
    if gate.get("verdict") != "green":
        return {"verdict": "blocked", "action": "merge-if-ready", "gate": gate}, 5
    if pr:
        host_verb(root, "merge", number=pr, method="merge")
    return {"verdict": "pass", "action": "merge-if-ready", "pr": pr, "hash": live_hash}, 0


def cmd_direct_trunk(root: Path, dry_run: bool) -> tuple[dict, int]:
    probe = probe_branch_protection(root)
    route = probe.get("route", "pr")
    allow = probe.get("allowDirectTrunk")
    if route != "direct" or not allow:
        return {"verdict": "fail", "action": "direct-trunk", "error": "direct-trunk-refused", "probe": probe}, 13
    if dry_run:
        return {"verdict": "pass", "action": "direct-trunk", "dry_run": True}, 0
    pre = _premerge_check(root)
    if pre.get("verdict") != "pass":
        return pre, 3
    default = default_base_branch(root)
    host_remote = remote_name(load_workflow_config(root))
    subprocess.run(["git", "-C", str(root), "push", host_remote, default], check=False)
    return {"verdict": "pass", "action": "direct-trunk", "branch": default}, 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Two-track mechanical docs merge helper")
    parser.add_argument("command", choices=["open", "merge-if-ready", "premerge-check", "direct-trunk"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--hash", default="")
    parser.add_argument("--pr", default="")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.root.resolve()
    handlers = {
        "premerge-check": lambda: cmd_premerge_check(root, args.dry_run),
        "open": lambda: cmd_open(root, args.dry_run),
        "merge-if-ready": lambda: cmd_merge_if_ready(root, args.dry_run, args.hash, args.pr),
        "direct-trunk": lambda: cmd_direct_trunk(root, args.dry_run),
    }
    result, code = handlers[args.command]()
    print(json.dumps(result))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
