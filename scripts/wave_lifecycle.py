#!/usr/bin/env python3
"""Orchestrator worktree, forward-merge, teardown, and entry guards for /sw-deliver."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from wave_errors import fail_from_payload
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
    extra.pop("error", None)
    if extra.get("halt") or extra.get("cause"):
        from halt_resume import enrich_fail_extra

        enrich_fail_extra(git_toplevel(Path.cwd()), extra)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def parse_last_json_object(text: str) -> dict[str, Any]:
    """Return the last top-level JSON object from mixed subprocess stdout."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty stdout")
    decoder = json.JSONDecoder()
    last_obj: dict[str, Any] | None = None
    idx = 0
    while idx < len(raw):
        try:
            obj, end = decoder.raw_decode(raw, idx)
        except json.JSONDecodeError:
            idx += 1
            continue
        if isinstance(obj, dict):
            last_obj = obj
        idx = max(end, idx + 1)
    if last_obj is None:
        raise ValueError("no JSON object found")
    return last_obj


def provision_payload_from_stdout(text: str, *, worktree_name: str) -> dict[str, Any]:
    """Parse worktree provision stdout and validate required path/name fields."""
    captured = (text or "").strip()
    try:
        payload = parse_last_json_object(captured)
    except ValueError as exc:
        fail(
            "phase provision stdout missing JSON payload",
            exit_code=20,
            halt="blocked",
            cause="phase-provision:invalid-stdout",
            stdout=captured[-2000:],
            detail=str(exc),
        )
    path = payload.get("path") or payload.get("worktreePath")
    name = payload.get("name") or payload.get("worktreeName") or worktree_name
    if not path or not str(path).strip():
        fail(
            "phase provision payload missing path",
            exit_code=20,
            halt="blocked",
            cause="phase-provision:invalid-payload",
            stdout=captured[-2000:],
            payload=payload,
        )
    if not name or not str(name).strip():
        fail(
            "phase provision payload missing name",
            exit_code=20,
            halt="blocked",
            cause="phase-provision:invalid-payload",
            stdout=captured[-2000:],
            payload=payload,
        )
    payload.setdefault("path", path)
    payload.setdefault("worktreePath", path)
    payload.setdefault("name", name)
    payload.setdefault("worktreeName", name)
    return payload


def git_toplevel(start: Path) -> Path:
    """Canonical shared repo root, not the calling worktree's own toplevel.

    Worktree creation and deliver-state resolution must anchor to the primary
    checkout shared by all worktrees (PRD 049 R4/R28, `.sw/layout.md` "Deliver
    state canonicalization"). `git rev-parse --show-toplevel` returns the
    *calling* worktree's private root when invoked from a linked worktree,
    which would nest orchestrator/phase worktrees under themselves instead of
    the shared `.sw-worktrees/` directory. `--git-common-dir` always resolves
    to the shared `.git` regardless of which worktree is calling.
    """
    out = subprocess.check_output(
        ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
        text=True,
    ).strip()
    common = Path(out)
    if not common.is_absolute():
        common = (Path(start) / common).resolve()
    return common.parent.resolve()


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


def load_deliver_state(root: Path) -> dict[str, Any]:
    from wave_state import load_deliver_state as _load

    return _load(root)


def save_deliver_state(root: Path, state: dict[str, Any]) -> None:
    from wave_state import save_deliver_state as _save

    _save(root, state)


def dependents_of(plan: dict[str, Any], phase_id: str) -> list[str]:
    return sorted(
        str(edge.get("to"))
        for edge in plan.get("edges") or []
        if str(edge.get("from")) == phase_id
    )


def dependent_references_worktree(
    state: dict[str, Any],
    plan: dict[str, Any],
    phase_id: str,
    worktree_path: str,
) -> bool:
    for dep_id in dependents_of(plan, phase_id):
        meta = (state.get("phases") or {}).get(dep_id, {})
        if not isinstance(meta, dict):
            continue
        if meta.get("status") not in ("pending", "in-flight"):
            continue
        wt_info = (state.get("phaseWorktrees") or {}).get(dep_id) or {}
        if str(wt_info.get("path") or "") == worktree_path:
            return True
    return False


def slug_from_target(target_branch: str) -> str:
    if "/" not in target_branch:
        fail(f"invalid target branch: {target_branch!r}")
    return target_branch.split("/", 1)[1]


def cmd_assert_entry(root: Path, args: list[str]) -> None:
    script = root / "scripts" / "sw-assert-worktree.py"
    if not script.is_file():
        fail("sw-assert-worktree.py missing", exit_code=2)
    proc = subprocess.run([sys.executable, str(script)], cwd=str(root), capture_output=True, text=True)
    if proc.returncode == 0:
        emit({"verdict": "pass", "action": "assert-entry", "allowed": True})
    if proc.returncode == 1:
        provision_args: list[str] = []
        target = parse_kv(args, "--target")
        plan_rel = parse_kv(args, "--plan")
        if target:
            provision_args.extend(["--target", target])
        elif plan_rel:
            provision_args.extend(["--plan", plan_rel])
        else:
            default_plan = root / ".cursor" / "sw-deliver-plan.json"
            if default_plan.is_file():
                provision_args.extend(["--plan", ".cursor/sw-deliver-plan.json"])
        if not provision_args:
            fail(
                proc.stderr.strip() or "implementation entry blocked on bare default branch",
                exit_code=1,
                halt="bare-main",
                remediation="provide --plan or --target for auto-provision",
            )
        cmd_orchestrator_provision(root, provision_args)
        emit(
            {
                "verdict": "pass",
                "action": "assert-entry",
                "allowed": True,
                "autoProvisioned": True,
            }
        )
    fail(proc.stderr.strip() or "worktree guard configuration error", exit_code=2)


def assert_primary_off_target(start: Path, target: str) -> None:
    """Primary checkout must not be on the orchestrator-owned branch (PRD 050 R1/R6)."""
    from primary_checkout_guard import (
        acquire_primary_lock,
        canonical_repo_root,
        primary_worktree_path,
        release_primary_lock,
    )

    repo_root = canonical_repo_root(start)
    primary = primary_worktree_path(repo_root)
    current = git_run(["branch", "--show-current"], primary, check=False).stdout.strip()
    if current != target:
        return
    status = git_run(["status", "--porcelain"], primary, check=False).stdout
    if status.strip():
        fail(
            f"primary checkout is dirty on {target} — commit, stash, and move off before orchestrator provision",
            exit_code=20,
            halt="dirty-primary",
            remediation=(
                f"git stash push -m 'pre-deliver' && git checkout $(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo main)"
            ),
        )
    default_ref = git_run(
        ["symbolic-ref", "refs/remotes/origin/HEAD"],
        repo_root,
        check=False,
    ).stdout.strip()
    if default_ref.startswith("refs/remotes/origin/"):
        default_branch = default_ref.removeprefix("refs/remotes/origin/")
    else:
        default_branch = "main"
    trunk_script = repo_root / "scripts" / "resolve_base_branch.py"
    if trunk_script.is_file():
        proc = subprocess.run(
            [sys.executable, str(trunk_script), "trunk-name"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            default_branch = proc.stdout.strip()
    lock = acquire_primary_lock(repo_root)
    if lock.get("verdict") != "pass":
        fail(
            lock.get("error", "primary checkout lock held"),
            exit_code=20,
            halt="primary-lock-held",
            remediation=lock.get("remediation"),
        )
    try:
        checkout = git_run(["checkout", default_branch], cwd=primary, check=False)
    finally:
        release_primary_lock(repo_root)
    if checkout.returncode != 0:
        fail(
            f"primary checkout is on {target}; auto-checkout to {default_branch!r} failed",
            exit_code=20,
            halt="primary-on-target",
            remediation=f"git checkout {default_branch}  # orchestrator worktree owns {target}",
            stderr=checkout.stderr.strip(),
        )



def orchestrator_worktree_branch(path: Path) -> str:
    return git_run(["branch", "--show-current"], cwd=path, check=False).stdout.strip()


def orchestrator_worktree_dirty(path: Path) -> bool:
    status = git_run(["status", "--porcelain"], cwd=path, check=False).stdout
    return bool(status.strip())


def adopt_orchestrator_worktree(
    root: Path,
    *,
    top: Path,
    path: Path,
    name: str,
    target: str,
    tip: str,
) -> None:
    from wave_state import load_deliver_state, resolve_state_path, save_deliver_state

    write_shipwright_state(
        path,
        {
            "worktreeName": name,
            "worktreePath": str(path),
            "worktreeRole": ORCHESTRATOR_ROLE,
            "countsTowardCeiling": False,
            "parentBranch": target,
            "currentBranch": target,
            "targetBranch": target,
            "detachedHead": False,
            "head": tip,
            "startedAt": utc_now(),
        },
    )
    state_path = resolve_state_path(top, target=target)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = load_deliver_state(top, target=target)
    state["orchestratorWorktree"] = {
        "name": name,
        "path": str(path),
        "branch": target,
        "countsTowardCeiling": False,
        "detachedHead": False,
        "head": tip,
    }
    save_deliver_state(top, state, target=target)



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
    assert_primary_off_target(top, target)
    wt_root = top / ".sw-worktrees"
    wt_root.mkdir(parents=True, exist_ok=True)
    path = wt_root / name
    if path.exists():
        if not path.is_dir() or not (path / ".git").exists():
            fail(
                f"orchestrator worktree path exists but is not a worktree: {path}",
                exit_code=20,
                halt="orchestrator-path-conflict",
                remediation=f"remove or relocate {path} before provisioning",
            )
        current = orchestrator_worktree_branch(path)
        if current != target:
            fail(
                f"orchestrator worktree on {current!r}, expected {target!r}",
                exit_code=20,
                halt="orchestrator-branch-mismatch",
                remediation=f"git -C {path} checkout {target}",
            )
        if orchestrator_worktree_dirty(path):
            fail(
                f"orchestrator worktree is dirty: {path}",
                exit_code=20,
                halt="dirty-orchestrator",
                remediation=f"commit or stash changes in {path} before adopt",
            )
        tip = git_run(["rev-parse", "HEAD"], cwd=path).stdout.strip()
        adopt_orchestrator_worktree(
            root, top=top, path=path, name=name, target=target, tip=tip
        )
        emit(
            {
                "verdict": "pass",
                "action": "orchestrator-provision",
                "path": str(path),
                "branch": target,
                "countsTowardCeiling": False,
                "adopted": True,
            }
        )

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
    git_run(["worktree", "add", "-B", target, str(path), ref], cwd=top)
    checked_out_branch = target

    adopt_orchestrator_worktree(
        root, top=top, path=path, name=name, target=target, tip=tip
    )

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
    from wave_state import load_deliver_state

    state = load_deliver_state(git_toplevel(root))
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

    mat_script = top / "scripts" / "planning_materialize.py"
    if mat_script.is_file():
        subprocess.run(
            [
                sys.executable,
                str(mat_script),
                "--root",
                str(top),
                "teardown",
                "--worktree",
                target,
            ],
            cwd=str(top),
            capture_output=True,
            text=True,
        )

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


def cmd_phase_teardown_run(root: Path, args: list[str]) -> None:
    """Safe eager teardown after green-merged + verify (R17)."""
    phase_id = parse_kv(args, "--phase-id")
    if not phase_id:
        fail("--phase-id required")
    plan = load_plan(root, parse_kv(args, "--plan"))
    state = load_deliver_state(root)
    phases = state.get("phases") or {}
    meta = phases.get(phase_id)
    if not isinstance(meta, dict):
        fail(f"unknown phase id: {phase_id}")
    if meta.get("status") not in ("green-merged", "teardown-pending"):
        fail(
            f"phase {phase_id} not ready for teardown (status={meta.get('status')!r})",
            exit_code=20,
        )

    target_branch = (state.get("target") or {}).get("branch")
    if not target_branch:
        fail("run-state missing target branch")

    wt_info = (state.get("phaseWorktrees") or {}).get(phase_id) or {}
    wt_path = str(wt_info.get("path") or "")
    if not wt_path or not Path(wt_path).is_dir():
        meta["status"] = "teardown-complete"
        meta["updatedAt"] = utc_now()
        phases[phase_id] = meta
        worktrees = state.get("phaseWorktrees") or {}
        worktrees.pop(phase_id, None)
        state["phaseWorktrees"] = worktrees
        save_deliver_state(root, state)
        emit(
            {
                "verdict": "pass",
                "action": "phase-teardown-run",
                "phaseId": phase_id,
                "note": "worktree already absent; marked teardown-complete",
            }
        )

    meta["status"] = "teardown-pending"
    meta["updatedAt"] = utc_now()
    phases[phase_id] = meta
    save_deliver_state(root, state)

    forward_merged: list[str] = []
    for dep_id in dependents_of(plan, phase_id):
        dep_meta = (phases.get(dep_id) or {}) if isinstance(phases.get(dep_id), dict) else {}
        if dep_meta.get("status") not in ("pending", "in-flight"):
            continue
        dep_wt_info = (state.get("phaseWorktrees") or {}).get(dep_id) or {}
        dep_wt = str(dep_wt_info.get("path") or "")
        if not dep_wt or not Path(dep_wt).is_dir():
            continue
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                str(root),
                "forward-merge",
                "--worktree",
                dep_wt,
                "--base",
                target_branch,
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            forward_merged.append(dep_id)
        elif proc.returncode == 20:
            fail(
                "forward-merge conflict blocks teardown",
                exit_code=20,
                halt="blocked",
                cause="forward-merge:conflict",
                dependentPhaseId=dep_id,
            )
        else:
            try:
                err = json.loads(proc.stdout)
            except json.JSONDecodeError:
                err = {"error": proc.stderr or proc.stdout}
            fail_from_payload(fail, err, "forward-merge failed", proc.returncode)

    if dependent_references_worktree(state, plan, phase_id, wt_path):
        fail(
            "dependent phase still references worktree path",
            exit_code=20,
            halt="blocked",
            cause="teardown:dependent-reference",
            phaseId=phase_id,
        )

    slug = meta.get("slug", phase_id)
    status_retained = (
        root / ".cursor" / "sw-deliver-runs" / str(slug) / "status.json"
    ).is_file()
    branch_retained = bool(meta.get("branch"))

    teardown_args = ["phase-teardown", "--worktree", wt_path]
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), str(root), *teardown_args],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout)
        except json.JSONDecodeError:
            err = {"error": proc.stderr or proc.stdout}
        fail_from_payload(fail, err, "phase teardown failed", proc.returncode)

    state = load_deliver_state(root)
    phases = state.setdefault("phases", {})
    meta = phases.get(phase_id, {})
    if isinstance(meta, dict):
        meta["status"] = "teardown-complete"
        meta["updatedAt"] = utc_now()
        meta["teardownAt"] = utc_now()
        phases[phase_id] = meta
    worktrees = state.get("phaseWorktrees") or {}
    worktrees.pop(phase_id, None)
    state["phaseWorktrees"] = worktrees
    save_deliver_state(root, state)

    emit(
        {
            "verdict": "pass",
            "action": "phase-teardown-run",
            "phaseId": phase_id,
            "phaseSlug": slug,
            "forwardMergedDependents": forward_merged,
            "retainedBranchRef": branch_retained,
            "retainedStatusJson": status_retained,
            "worktreeRemoved": wt_path,
        }
    )




def worktree_current_branch(wt_path: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(wt_path), "branch", "--show-current"],
        text=True,
        capture_output=True,
    )
    branch = proc.stdout.strip() if proc.returncode == 0 else ""
    return branch or None


def adopt_orphan_phase_worktree(
    root: Path,
    *,
    phase_id: str,
    wt_path: Path,
    name: str,
    branch: str,
    slug: str,
    base: str,
) -> dict[str, Any]:
    """Register an existing matching orphan worktree in durable state (R7)."""
    state = load_deliver_state(root)
    worktrees = state.setdefault("phaseWorktrees", {})
    worktrees[str(phase_id)] = {"name": name, "path": str(wt_path)}
    state["phaseWorktrees"] = worktrees
    save_deliver_state(root, state)
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
    return {
        "verdict": "pass",
        "action": "phase-provision",
        "adopted": True,
        "path": str(wt_path),
        "name": name,
        "worktreeName": name,
        "branch": branch,
        "countsTowardCeiling": True,
        "worktreeRole": PHASE_ROLE,
    }


def reconcile_orphan_phase_worktree(
    root: Path,
    *,
    phase_id: str,
    wt_path: Path,
    name: str,
    expected_branch: str,
    slug: str,
    base: str,
) -> dict[str, Any] | None:
    """Adopt matching orphan into state or teardown mismatch before retry (R7/R8)."""
    if not wt_path.is_dir():
        return None
    state = load_deliver_state(root)
    recorded = (state.get("phaseWorktrees") or {}).get(str(phase_id))
    if isinstance(recorded, dict) and recorded.get("path"):
        return None
    actual = worktree_current_branch(wt_path)
    if actual == expected_branch:
        return adopt_orphan_phase_worktree(
            root,
            phase_id=str(phase_id),
            wt_path=wt_path,
            name=name,
            branch=expected_branch,
            slug=slug,
            base=base,
        )
    teardown_args = ["phase-teardown", "--worktree", str(wt_path)]
    if actual and actual != expected_branch:
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(root), *teardown_args],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            try:
                err = json.loads(proc.stdout)
            except json.JSONDecodeError:
                err = {"error": proc.stderr or proc.stdout}
            fail_from_payload(fail, err, "orphan worktree teardown failed", proc.returncode)
    return None

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
    wt_path = top / ".sw-worktrees" / name
    adopted = reconcile_orphan_phase_worktree(
        root,
        phase_id=str(phase_id),
        wt_path=wt_path,
        name=name,
        expected_branch=str(branch),
        slug=str(slug),
        base=str(base),
    )
    if adopted is not None:
        emit(adopted)
        return

    script = top / "scripts" / "worktree.py"
    proc = subprocess.run(
        [
            sys.executable,
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
        would_free: list[str] = []
        for _pid, meta in (load_deliver_state(root).get("phases") or {}).items():
            if isinstance(meta, dict) and meta.get("status") == "teardown-pending":
                wt_info = (load_deliver_state(root).get("phaseWorktrees") or {}).get(str(_pid), {})
                name = wt_info.get("name") if isinstance(wt_info, dict) else None
                if name:
                    would_free.append(str(name))
        fail(
            "parallel ceiling reached",
            exit_code=10,
            halt="ceiling",
            wouldFree=len(would_free),
            worktrees=would_free,
            recommendedCommand="/sw-cleanup",
            note="Run phase-teardown or /sw-cleanup to free slots (R45)",
        )
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

    task_list = plan.get("source_task_list")
    if task_list and wt_path.is_dir():
        mat_proc = subprocess.run(
            [
                sys.executable,
                str(top / "scripts" / "planning_materialize.py"),
                "--root",
                str(top),
                "provision",
                "--worktree",
                str(wt_path),
                "--task-list",
                str(task_list),
                "--target",
                base,
            ],
            cwd=str(top),
            capture_output=True,
            text=True,
        )
        if mat_proc.returncode == 20:
            try:
                err = json.loads(mat_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": mat_proc.stderr or mat_proc.stdout}
            fail_from_payload(fail, err, "materialize provision failed", 20)
        if mat_proc.returncode not in (0,):
            fail(
                mat_proc.stderr.strip() or mat_proc.stdout.strip() or "materialize provision failed",
                exit_code=mat_proc.returncode,
            )

    payload = provision_payload_from_stdout(proc.stdout, worktree_name=name)
    payload["countsTowardCeiling"] = True
    payload["worktreeRole"] = PHASE_ROLE
    emit({"verdict": "pass", "action": "phase-provision", **payload})



def cmd_execute_provision_sub_branch(root: Path, args: list[str]) -> None:
    import subprocess

    script = root / "scripts" / "execute_plan.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(root), "provision-sub-branch", *args],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "execute sub-branch provision failed", exit_code=proc.returncode)


def cmd_execute_teardown_sub_branch(root: Path, args: list[str]) -> None:
    import subprocess

    script = root / "scripts" / "execute_plan.py"
    proc = subprocess.run(
        [sys.executable, str(script), str(root), "teardown-sub-branch", *args],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.stdout:
        sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "execute sub-branch teardown failed", exit_code=proc.returncode)

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
    elif cmd == "phase-teardown-run":
        cmd_phase_teardown_run(root, args)
    elif cmd == "execute":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "provision-sub-branch":
            cmd_execute_provision_sub_branch(root, rest)
        elif sub == "teardown-sub-branch":
            cmd_execute_teardown_sub_branch(root, rest)
        else:
            fail("execute subcommand required: provision-sub-branch|teardown-sub-branch")
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
