#!/usr/bin/env python3
"""Orchestrator worktree, forward-merge, teardown, and entry guards for /sw-deliver."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ORCHESTRATOR_ROLE = "orchestrator"
PHASE_ROLE = "phase"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def git_toplevel(start: Path) -> Path:
    out = subprocess.check_output(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
    ).strip()
    return Path(out)


def git_run(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = ["git"] + args
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=check,
    )


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_shipwright_state(worktree_path: Path, payload: dict[str, Any]) -> None:
    gitdir_line = (worktree_path / ".git").read_text(encoding="utf-8").splitlines()[0]
    m = re.match(r"gitdir:\s*(.+)", gitdir_line)
    if not m:
        fail(f"cannot resolve gitdir for worktree: {worktree_path}")
    state_path = Path(m.group(1).strip()) / "shipwright.json"
    state_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(state_path, 0o600)


def load_plan(root: Path, plan_rel: str | None) -> dict[str, Any]:
    rel = plan_rel or ".cursor/sw-deliver-plan.json"
    plan_path = (root / rel).resolve()
    if not plan_path.is_file():
        fail(f"plan not found: {rel}")
    try:
        return json.loads(plan_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid plan JSON: {exc}")


def slug_from_target(target_branch: str) -> str:
    if "/" not in target_branch:
        fail(f"invalid target branch: {target_branch!r}")
    return target_branch.split("/", 1)[1]


def cmd_assert_entry(root: Path, _args: list[str]) -> None:
    script = root / "scripts" / "sw-assert-worktree.sh"
    if not script.is_file():
        fail("sw-assert-worktree.sh missing", exit_code=2)
    proc = subprocess.run(["bash", str(script)], cwd=str(root), capture_output=True, text=True)
    if proc.returncode == 0:
        emit({"verdict": "pass", "action": "assert-entry", "allowed": True})
    if proc.returncode == 1:
        fail(
            proc.stderr.strip() or "implementation entry blocked on bare default branch",
            exit_code=1,
            halt="bare-main",
        )
    fail(proc.stderr.strip() or "worktree guard configuration error", exit_code=2)


def cmd_orchestrator_provision(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if not target:
        plan = load_plan(root, parse_kv(args, "--plan"))
        target = (plan.get("target") or {}).get("branch")
    if not target:
        fail("--target or --plan with target.branch required")
    slug = slug_from_target(target)
    name = parse_kv(args, "--name", f"{slug}-orchestrator") or f"{slug}-orchestrator"
    top = git_toplevel(root)
    wt_root = top / ".sw-worktrees"
    wt_root.mkdir(parents=True, exist_ok=True)
    path = wt_root / name
    if path.exists():
        fail(f"orchestrator worktree already exists: {path}", exit_code=20)

    git_run(["fetch", "origin", target], cwd=top, check=False)
    ref = target
    show = git_run(["show-ref", "--verify", f"refs/heads/{target}"], cwd=top, check=False)
    if show.returncode != 0:
        remote = git_run(
            ["show-ref", "--verify", f"refs/remotes/origin/{target}"],
            cwd=top,
            check=False,
        )
        if remote.returncode == 0:
            ref = f"origin/{target}"
        else:
            fail(f"base branch not found locally or on origin: {target}")

    tip = git_run(["rev-parse", ref], cwd=top).stdout.strip()
    current = git_run(["branch", "--show-current"], cwd=top, check=False).stdout.strip()
    add_args = ["worktree", "add"]
    if current == target:
        add_args.extend(["--detach", str(path), tip])
        checked_out_branch = None
    else:
        add_args.extend(["-B", target, str(path), ref])
        checked_out_branch = target
    git_run(add_args, cwd=top)

    write_shipwright_state(
        path,
        {
            "worktreeName": name,
            "worktreePath": str(path),
            "worktreeRole": ORCHESTRATOR_ROLE,
            "countsTowardCeiling": False,
            "parentBranch": target,
            "currentBranch": checked_out_branch or target,
            "targetBranch": target,
            "detachedHead": checked_out_branch is None,
            "head": tip,
            "startedAt": utc_now(),
        },
    )

    state_path = root / ".cursor" / "sw-deliver-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = read_json(state_path)
    state["orchestratorWorktree"] = {
        "name": name,
        "path": str(path),
        "branch": target,
        "countsTowardCeiling": False,
        "detachedHead": checked_out_branch is None,
        "head": tip,
    }
    state["updatedAt"] = utc_now()
    state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.chmod(state_path, 0o600)

    emit(
        {
            "verdict": "pass",
            "action": "orchestrator-provision",
            "path": str(path),
            "branch": target,
            "countsTowardCeiling": False,
        }
    )


def cmd_orchestrator_status(root: Path, _args: list[str]) -> None:
    state = read_json(root / ".cursor" / "sw-deliver-state.json")
    orch = state.get("orchestratorWorktree")
    if not orch:
        emit({"verdict": "pass", "provisioned": False})
    path = Path(orch.get("path", ""))
    emit(
        {
            "verdict": "pass",
            "provisioned": path.is_dir(),
            "orchestratorWorktree": orch,
        }
    )


def cmd_forward_merge(root: Path, args: list[str]) -> None:
    worktree = parse_kv(args, "--worktree")
    base = parse_kv(args, "--base")
    if not worktree or not base:
        fail("--worktree and --base required")
    wt_path = Path(worktree).resolve()
    if not wt_path.is_dir():
        fail(f"worktree not found: {worktree}")

    git_run(["fetch", "origin", base], cwd=wt_path, check=False)
    merge_ref = base
    local = git_run(["show-ref", "--verify", f"refs/heads/{base}"], cwd=wt_path, check=False)
    if local.returncode != 0:
        remote = git_run(
            ["show-ref", "--verify", f"refs/remotes/origin/{base}"],
            cwd=wt_path,
            check=False,
        )
        if remote.returncode == 0:
            merge_ref = f"origin/{base}"
        else:
            fail(f"base branch not found for forward-merge: {base}")

    proc = git_run(["merge", merge_ref, "--no-edit"], cwd=wt_path, check=False)
    if proc.returncode != 0:
        merge_active = (
            git_run(["rev-parse", "-q", "--verify", "MERGE_HEAD"], cwd=wt_path, check=False).returncode
            == 0
        )
        if merge_active or "CONFLICT" in (proc.stdout + proc.stderr).upper():
            git_run(["merge", "--abort"], cwd=wt_path, check=False)
            fail(
                "forward-merge conflict",
                exit_code=20,
                halt="blocked",
                cause="forward-merge:conflict",
                base=base,
                worktree=str(wt_path),
            )
        fail(proc.stderr.strip() or proc.stdout.strip() or "forward-merge failed")

    head = git_run(["rev-parse", "HEAD"], cwd=wt_path).stdout.strip()
    emit(
        {
            "verdict": "pass",
            "action": "forward-merge",
            "base": base,
            "worktree": str(wt_path),
            "head": head,
        }
    )


def cmd_phase_teardown(root: Path, args: list[str]) -> None:
    worktree = parse_kv(args, "--worktree")
    name = parse_kv(args, "--name")
    force = "--force" in args
    if not worktree and not name:
        fail("--worktree or --name required")
    top = git_toplevel(root)
    if worktree:
        target = str(Path(worktree).resolve())
    else:
        target = str(top / ".sw-worktrees" / name)

    if " rm " in target or target.endswith("/rm"):
        fail("refused: never rm a worktree directory — use git worktree remove", exit_code=2)

    if not Path(target).is_dir():
        fail(f"worktree not found: {target}")

    before_kb = 0
    try:
        du = subprocess.check_output(["du", "-sk", target], text=True)
        before_kb = int(du.split()[0])
    except (subprocess.CalledProcessError, ValueError, IndexError):
        pass

    remove_args = ["worktree", "remove", target]
    if force:
        remove_args.append("--force")
    git_run(remove_args, cwd=top)
    git_run(["worktree", "prune"], cwd=top)

    emit(
        {
            "verdict": "pass",
            "action": "phase-teardown",
            "path": target,
            "diskReclaimedKb": before_kb,
        }
    )


def cmd_phase_provision(root: Path, args: list[str]) -> None:
    phase_id = parse_kv(args, "--phase-id")
    if not phase_id:
        fail("--phase-id required")
    plan = load_plan(root, parse_kv(args, "--plan"))
    items = plan.get("items") or []
    item = next((i for i in items if str(i.get("id")) == phase_id), None)
    if not item:
        fail(f"phase id {phase_id!r} not found in plan")
    branch = item.get("branch")
    if not branch:
        fail(f"plan item {phase_id} missing branch")
    base = parse_kv(args, "--base") or (plan.get("target") or {}).get("branch")
    if not base:
        fail("--base or plan.target.branch required")
    slug = item.get("slug", phase_id)
    target_slug = slug_from_target((plan.get("target") or {}).get("branch", "feat/x"))
    name = parse_kv(args, "--name", f"{target_slug}-phase-{slug}") or f"{target_slug}-phase-{slug}"

    top = git_toplevel(root)
    script = top / "scripts" / "worktree.sh"
    proc = subprocess.run(
        [
            "bash",
            str(script),
            "provision",
            name,
            "--branch",
            branch,
            "--base",
            base,
        ],
        cwd=str(top),
        capture_output=True,
        text=True,
    )
    if proc.returncode == 10:
        fail("parallel ceiling reached", exit_code=10, halt="ceiling")
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "phase provision failed")

    wt_path = top / ".sw-worktrees" / name
    if wt_path.is_dir():
        write_shipwright_state(
            wt_path,
            {
                "worktreeName": name,
                "worktreePath": str(wt_path),
                "worktreeRole": PHASE_ROLE,
                "countsTowardCeiling": True,
                "parentBranch": base,
                "currentBranch": branch,
                "phaseId": phase_id,
                "phaseSlug": slug,
                "startedAt": utc_now(),
            },
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        payload = {"raw": proc.stdout.strip()}
    payload["countsTowardCeiling"] = True
    payload["worktreeRole"] = PHASE_ROLE
    emit({"verdict": "pass", "action": "phase-provision", **payload})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_lifecycle.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]

    if cmd == "assert-entry":
        cmd_assert_entry(root, args)
    elif cmd == "orchestrator":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "provision":
            cmd_orchestrator_provision(root, rest)
        elif sub == "status":
            cmd_orchestrator_status(root, rest)
        else:
            fail("orchestrator subcommand required: provision|status")
    elif cmd == "forward-merge":
        cmd_forward_merge(root, args)
    elif cmd == "phase-teardown":
        cmd_phase_teardown(root, args)
    elif cmd == "phase":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "provision":
            cmd_phase_provision(root, rest)
        else:
            fail("phase subcommand required: provision")
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
