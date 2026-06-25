#!/usr/bin/env python3
"""Merge queue, review barrier, status collection, and terminal report for /sw-deliver.

Concurrency contract (R21/R22/R41): only the conductor calls `merge enqueue` / `merge run-next`.
`merge run-next` authorizes via gate + review barrier, merges onto `<type>/<slug>` never `main`,
and runs single-flight via merge journal + orchestrator lock (`wave_state.py` O_EXCL acquire).

Status collect (R19/R24): reads durable `status.json` only; `blocked` triggers blast-radius apply
on transitive dependents — green siblings in the same wave continue.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_json_io import StateCorruptError, read_json, write_json
from wave_state import assert_phase_status

VALID_STATUS_VERDICTS = frozenset({"merge-ready-green", "blocked"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def fail_payload(data: dict[str, Any], default: str, exit_code: int, **extra: Any) -> None:
    reserved = {"error", *extra.keys()}
    payload = {k: v for k, v in data.items() if k not in reserved}
    fail(data.get("error") or default, exit_code=exit_code, **extra, **payload)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def state_path(root: Path) -> Path:
    return root / ".cursor" / "sw-deliver-state.json"


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    try:
        return read_json(path)
    except StateCorruptError as exc:
        fail(
            f"corrupt durable state: {exc}",
            exit_code=20,
            halt="blocked",
            cause="state:corrupt",
            path=str(path),
        )
        return {}


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["updatedAt"] = utc_now()
    write_json(state_path(root), state)


def phase_already_merged(top: Path, phase_branch: str, target: str) -> bool:
    try:
        phase_sha = git_run(["rev-parse", phase_branch], cwd=top, check=True).stdout.strip()
        target_sha = git_run(["rev-parse", target], cwd=top, check=True).stdout.strip()
        proc = git_run(
            ["merge-base", "--is-ancestor", phase_sha, target_sha],
            cwd=top,
            check=False,
        )
        return proc.returncode == 0
    except subprocess.CalledProcessError:
        return False


def clear_open_journal_if_merged(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Idempotent crash recovery: open journal + phase already on target → clear journal (R45)."""
    journal = state.get("mergeJournal")
    if not journal:
        return state
    phase_slug = journal.get("phase", "")
    phases = state.get("phases") or {}
    phase_branch = None
    for meta in phases.values():
        if meta.get("slug") == phase_slug:
            phase_branch = meta.get("branch")
            break
    target = (state.get("target") or {}).get("branch")
    if not phase_branch or not target:
        return state
    top = root
    if phase_already_merged(top, phase_branch, target):
        key = journal.get("key") or phase_slug
        done = list(state.get("completedMerges") or [])
        if not any(isinstance(c, dict) and c.get("key") == key for c in done):
            done.append(
                {
                    "key": key,
                    "phase": phase_slug,
                    "head": journal.get("head"),
                    "completedAt": utc_now(),
                    "recovered": True,
                }
            )
        state["completedMerges"] = done
        state["mergeJournal"] = None
        save_state(root, state)
    return state


def git_run(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=check,
    )


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = root / "scripts" / "check-gate.sh"
    cmd = ["bash", str(script)]
    if pr:
        cmd.append(pr)
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
    try:
        gate = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        gate = {"verdict": "blocked", "reason": proc.stderr.strip() or "invalid gate output"}
    return proc.returncode, gate


def merge_authorizing(gate_ec: int, gate: dict[str, Any]) -> bool:
    if gate_ec != 0 or gate.get("verdict") != "green":
        return False
    if gate.get("coderabbitLanded") is False:
        return False
    return True


def status_file_for(
    root: Path,
    phase_slug: str,
    explicit: str | None,
    state: dict[str, Any] | None = None,
) -> Path:
    if explicit:
        return Path(explicit).resolve()
    if state is None and state_path(root).is_file():
        state = load_state(root)
    wt = resolve_phase_worktree(root, phase_slug, state or {})
    if wt is not None:
        candidate = wt / ".cursor" / "sw-deliver-runs" / phase_slug / "status.json"
        if candidate.is_file():
            return candidate
    return root / ".cursor" / "sw-deliver-runs" / phase_slug / "status.json"


def resolve_phase_worktree(
    root: Path, phase_slug: str, state: dict[str, Any]
) -> Path | None:
    phases = state.get("phases") or {}
    phase_id: str | None = None
    for pid, meta in phases.items():
        if isinstance(meta, dict) and meta.get("slug") == phase_slug:
            phase_id = str(pid)
            break
    if not phase_id:
        return None
    wt_info = (state.get("phaseWorktrees") or {}).get(phase_id) or {}
    if not isinstance(wt_info, dict):
        return None
    raw = wt_info.get("path")
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = (root / path).resolve()
    return path if path.is_dir() else None


def phase_meta_for_slug(state: dict[str, Any], phase_slug: str) -> tuple[str | None, dict[str, Any]]:
    for pid, meta in (state.get("phases") or {}).items():
        if isinstance(meta, dict) and meta.get("slug") == phase_slug:
            return str(pid), meta
    return None, {}


def phase_branch_head(root: Path, state: dict[str, Any], phase_slug: str, phase_branch: str) -> str:
    head = phase_branch_head_optional(root, state, phase_slug, phase_branch)
    if not head:
        fail(f"could not resolve head for {phase_branch!r}", phase=phase_slug)
    return head


def phase_branch_head_optional(
    root: Path, state: dict[str, Any], phase_slug: str, phase_branch: str
) -> str | None:
    wt = resolve_phase_worktree(root, phase_slug, state)
    for cwd in (wt, root):
        if cwd is None:
            continue
        proc = git_run(["rev-parse", phase_branch], cwd=cwd, check=False)
        head = proc.stdout.strip()
        if proc.returncode == 0 and head:
            return head
    return None


def check_status_sha(status: dict[str, Any], expected_head: str) -> tuple[bool, str | None]:
    recorded = status.get("head")
    if not recorded:
        return False, "phase-status:missing-head"
    if str(recorded) != expected_head:
        return False, "phase-status:stale"
    return True, None


def validate_status_sha(status: dict[str, Any], expected_head: str, phase_slug: str) -> None:
    ok, cause = check_status_sha(status, expected_head)
    if not ok:
        fail(
            "stale phase status: head SHA does not match branch tip"
            if cause == "phase-status:stale"
            else "status missing head SHA binding",
            exit_code=20,
            halt="blocked",
            cause=cause,
            phase=phase_slug,
            statusHead=status.get("head"),
            branchHead=expected_head,
        )


def local_evidence_authorizing(status: dict[str, Any], expected_head: str) -> bool:
    """No-PR path: merge-ready-green + head binding + optional embedded gate evidence (R39/R54)."""
    if status.get("verdict") != "merge-ready-green":
        return False
    if str(status.get("head") or "") != expected_head:
        return False
    gate = status.get("gate")
    if gate is None:
        return True
    if not isinstance(gate, dict):
        return False
    if gate.get("verdict") != "green":
        return False
    if gate.get("coderabbitLanded") is False:
        return False
    return True


def authorize_merge(
    root: Path,
    state: dict[str, Any],
    phase_slug: str,
    entry: dict[str, Any],
    status: dict[str, Any],
    phase_branch: str,
) -> tuple[bool, dict[str, Any], str]:
    expected_head = phase_branch_head(root, state, phase_slug, phase_branch)
    validate_status_sha(status, expected_head, phase_slug)

    pr = entry.get("pr")
    if pr is not None and str(pr).strip() not in ("", "null", "None"):
        gate_ec, gate = run_check_gate(root, str(pr))
        return merge_authorizing(gate_ec, gate), gate, "pr"

    local_ok = local_evidence_authorizing(status, expected_head)
    evidence = {
        "verdict": "green" if local_ok else "blocked",
        "source": "local-evidence",
        "statusHead": status.get("head"),
        "branchHead": expected_head,
        "embeddedGate": status.get("gate"),
    }
    return local_ok, evidence, "local"


def cmd_status_collect(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    state = load_state(root) if state_path(root).is_file() else {}
    path = status_file_for(root, phase_slug, parse_kv(args, "--path"), state)
    if not path.is_file():
        fail(
            f"phase status not found: {path}",
            exit_code=20,
            halt="blocked",
            cause="phase-status:missing",
            phase=phase_slug,
        )
    status = read_json(path)
    verdict = status.get("verdict")
    if verdict not in VALID_STATUS_VERDICTS:
        fail(
            f"invalid phase status verdict: {verdict!r}",
            exit_code=20,
            phase=phase_slug,
        )
    _, meta = phase_meta_for_slug(state, phase_slug)
    phase_branch = meta.get("branch")
    if phase_branch and verdict == "merge-ready-green":
        expected = phase_branch_head_optional(root, state, phase_slug, str(phase_branch))
        if expected:
            validate_status_sha(status, expected, phase_slug)
    if verdict == "blocked":
        state = load_state(root)
        phases = state.get("phases") or {}
        for pid, meta in phases.items():
            if meta.get("slug") == phase_slug:
                meta["status"] = "blocked"
                meta["updatedAt"] = utc_now()
                if status.get("cause"):
                    meta["cause"] = status["cause"]
                phases[pid] = meta
                break
        state["phases"] = phases
        save_state(root, state)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "wave_failure.py"),
                str(root),
                "blast-radius",
                "apply",
                "--phase-slug",
                phase_slug,
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
    emit(
        {
            "verdict": "pass",
            "action": "status-collect",
            "phase": phase_slug,
            "statusPath": str(path),
            "status": status,
        }
    )


def cmd_phase_dispatch_env(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug")
    if not phase_slug:
        fail("--phase-slug required")
    run_dir = f".cursor/sw-deliver-runs/{phase_slug}"
    emit(
        {
            "verdict": "pass",
            "action": "phase-dispatch-env",
            "phase": phase_slug,
            "exports": {
                "SW_PHASE_MODE": "1",
                "SW_PHASE_SLUG": phase_slug,
                "SW_RUN_DIR": run_dir,
            },
            "invoke": "/sw-ship --phase-mode",
            "note": "Run full /sw-ship chain in phase worktree; orchestrator does not bypass steps",
        }
    )


def cmd_merge_gate_check(root: Path, args: list[str]) -> None:
    pr = parse_kv(args, "--pr")
    gate_ec, gate = run_check_gate(root, pr)
    ready = merge_authorizing(gate_ec, gate)
    payload: dict[str, Any] = {
        "verdict": "pass" if ready else "wait",
        "mergeReady": ready,
        "gate": gate,
        "gateExitCode": gate_ec,
        "reviewBarrierSettled": gate.get("coderabbitLanded") is not False,
    }
    if not ready:
        payload["reason"] = gate.get("reason") or "gate not green or review not settled"
    emit(payload, 0 if ready else 10)


def cmd_merge_enqueue(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    state = load_state(root)
    status_path = status_file_for(root, phase_slug, parse_kv(args, "--status-path"), state)
    status = read_json(status_path)
    if status.get("verdict") != "merge-ready-green":
        fail(
            "only merge-ready-green phases may be enqueued",
            exit_code=20,
            status=status,
        )
    _, meta = phase_meta_for_slug(state, phase_slug)
    phase_branch = meta.get("branch")
    if phase_branch:
        expected = phase_branch_head_optional(root, state, phase_slug, str(phase_branch))
        if expected:
            validate_status_sha(status, expected, phase_slug)
    queue = list(state.get("mergeQueue") or [])
    if any(item.get("phaseSlug") == phase_slug for item in queue):
        emit({"verdict": "pass", "action": "merge-enqueue", "note": "already queued", "phase": phase_slug})
    entry = {
        "phaseSlug": phase_slug,
        "head": status.get("head"),
        "pr": status.get("pr"),
        "enqueuedAt": utc_now(),
    }
    queue.append(entry)
    state["mergeQueue"] = queue
    save_state(root, state)
    emit({"verdict": "pass", "action": "merge-enqueue", "entry": entry, "queueLength": len(queue)})


def resolve_orchestrator_worktree(root: Path, args: list[str]) -> Path:
    explicit = parse_kv(args, "--orchestrator-worktree")
    if explicit:
        return Path(explicit).resolve()
    state = load_state(root)
    orch = state.get("orchestratorWorktree") or {}
    path = orch.get("path")
    if not path:
        fail("orchestrator worktree not provisioned; run orchestrator provision first")
    return Path(path).resolve()


def cmd_merge_exec(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug")
    phase_branch = parse_kv(args, "--phase-branch")
    target = parse_kv(args, "--target")
    if not phase_slug or not phase_branch or not target:
        fail("--phase-slug, --phase-branch, and --target required")
    wt = resolve_orchestrator_worktree(root, args)
    git_run(["fetch", "origin", phase_branch, target], cwd=wt, check=False)
    merge_ref = phase_branch
    if git_run(["show-ref", "--verify", f"refs/heads/{phase_branch}"], cwd=wt, check=False).returncode != 0:
        if (
            git_run(
                ["show-ref", "--verify", f"refs/remotes/origin/{phase_branch}"],
                cwd=wt,
                check=False,
            ).returncode
            == 0
        ):
            merge_ref = f"origin/{phase_branch}"
        else:
            fail(f"phase branch not found: {phase_branch}")

    msg = parse_kv(args, "--message") or f"merge({target.split('/')[-1]}): phase {phase_slug}"
    proc = git_run(
        ["merge", "--no-ff", merge_ref, "-m", msg],
        cwd=wt,
        check=False,
    )
    if proc.returncode != 0:
        git_run(["merge", "--abort"], cwd=wt, check=False)
        fail(
            "merge failed",
            exit_code=20,
            halt="blocked",
            cause="merge-queue:conflict",
            stderr=proc.stderr.strip(),
        )
    head = git_run(["rev-parse", "HEAD"], cwd=wt).stdout.strip()
    emit(
        {
            "verdict": "pass",
            "action": "merge-exec",
            "phase": phase_slug,
            "mergeCommit": head,
            "method": "merge",
            "target": target,
        }
    )


def cmd_merge_ancestry_check(root: Path, args: list[str]) -> None:
    phase_branch = parse_kv(args, "--phase-branch")
    target = parse_kv(args, "--target")
    if not phase_branch or not target:
        fail("--phase-branch and --target required")
    top = Path(
        subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    phase_sha = git_run(["rev-parse", phase_branch], cwd=top, check=False).stdout.strip()
    target_sha = git_run(["rev-parse", target], cwd=top, check=False).stdout.strip()
    if not phase_sha or not target_sha:
        fail("could not resolve branch tips")
    proc = git_run(
        ["merge-base", "--is-ancestor", phase_sha, target_sha],
        cwd=top,
        check=False,
    )
    merged = proc.returncode == 0
    emit(
        {
            "verdict": "pass",
            "merged": merged,
            "phaseBranch": phase_branch,
            "target": target,
            "predicate": "git merge-base --is-ancestor <phase-tip> <target-tip>",
        }
    )


def cmd_merge_run_next(root: Path, args: list[str]) -> None:
    dry_run = "--dry-run" in args
    state = load_state(root)
    state = clear_open_journal_if_merged(root, state)
    if state.get("mergeJournal"):
        fail("merge already in flight", exit_code=20, journal=state["mergeJournal"])
    queue = list(state.get("mergeQueue") or [])
    if not queue:
        emit({"verdict": "pass", "action": "merge-run-next", "note": "queue empty"})
    entry = queue[0]
    phase_slug = entry.get("phaseSlug", "")
    pr = entry.get("pr")
    pr_str = str(pr) if pr is not None else None

    phases = state.get("phases") or {}
    phase_branch = None
    phase_id = None
    for pid, meta in phases.items():
        if meta.get("slug") == phase_slug:
            phase_branch = meta.get("branch")
            phase_id = pid
            break
    target = (state.get("target") or {}).get("branch")
    if not phase_branch or not target:
        fail("missing phase branch or target in run-state")

    status_path = status_file_for(root, phase_slug, None, state)
    if not status_path.is_file():
        fail(
            "phase status missing for merge",
            exit_code=20,
            halt="blocked",
            cause="phase-status:missing",
            phase=phase_slug,
            statusPath=str(status_path),
        )
    status = read_json(status_path)
    authorized, gate, auth_path = authorize_merge(
        root, state, phase_slug, entry, status, str(phase_branch)
    )
    if not authorized:
        fail(
            "review barrier / gate not satisfied",
            exit_code=10,
            halt="wait" if auth_path == "pr" else "blocked",
            gate=gate,
            phase=phase_slug,
            authPath=auth_path,
        )

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "merge-run-next",
                "dry_run": True,
                "phase": phase_slug,
                "phaseBranch": phase_branch,
                "target": target,
                "gate": gate,
                "authPath": auth_path,
            }
        )

    journal = {
        "phase": phase_slug,
        "head": status.get("head"),
        "startedAt": utc_now(),
        "key": phase_slug,
    }
    state["mergeJournal"] = journal
    save_state(root, state)

    merge_args = [
        "--phase-slug",
        phase_slug,
        "--phase-branch",
        phase_branch,
        "--target",
        target,
    ]
    orch = parse_kv(args, "--orchestrator-worktree")
    if orch:
        merge_args.extend(["--orchestrator-worktree", orch])

    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "wave_merge.py"), str(root), "merge", "exec", *merge_args],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            state = load_state(root)
            state["mergeJournal"] = None
            save_state(root, state)
            try:
                err = json.loads(proc.stdout)
            except json.JSONDecodeError:
                err = {"error": proc.stderr or proc.stdout}
            fail_payload(err, "merge failed", proc.returncode)

        merge_out = json.loads(proc.stdout)
        merge_commit = merge_out.get("mergeCommit")

        state = load_state(root)
        state["mergeQueue"] = queue[1:]
        state["mergeJournal"] = None
        done = list(state.get("completedMerges") or [])
        key = phase_slug
        if not any(isinstance(c, dict) and c.get("key") == key for c in done):
            done.append(
                {
                    "key": key,
                    "phase": phase_slug,
                    "head": None,
                    "completedAt": utc_now(),
                    "mergeCommit": merge_commit,
                }
            )
        state["completedMerges"] = done
        merged = list(state.get("mergedPhases") or [])
        merged.append(
            {
                "phaseSlug": phase_slug,
                "phaseId": phase_id,
                "pr": pr,
                "mergeCommit": merge_commit,
                "mergedAt": utc_now(),
            }
        )
        state["mergedPhases"] = merged
        if phase_id and phase_id in state.get("phases", {}):
            assert_phase_status("green-merged")
            state["phases"][phase_id]["status"] = "green-merged"
            state["phases"][phase_id]["updatedAt"] = utc_now()
            state["phases"][phase_id]["mergeCommit"] = merge_commit
        save_state(root, state)

        target_branch = (state.get("target") or {}).get("branch", "feat/unknown")
        commit_type = target_branch.split("/", 1)[0] if "/" in target_branch else "feat"
        if phase_id and phase_id in state.get("phases", {}):
            for record in state.get("mergedPhases") or []:
                if record.get("phaseSlug") == phase_slug:
                    record["commitType"] = commit_type
                    break
            save_state(root, state)

        bk_args = [
            sys.executable,
            str(SCRIPT_DIR / "wave_bookkeeping.py"),
            str(root),
            "record",
            "--phase-slug",
            phase_slug,
            "--message",
            f"merge phase {phase_slug} into {target_branch}",
            "--type",
            commit_type,
            "--merge-commit",
            merge_commit or "",
            "--commit",
        ]
        orch = parse_kv(args, "--orchestrator-worktree")
        if orch:
            bk_args.extend(["--worktree", orch])
        bk_proc = subprocess.run(bk_args, cwd=str(root), text=True, capture_output=True)
        if bk_proc.returncode != 0:
            try:
                err = json.loads(bk_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": bk_proc.stderr or bk_proc.stdout}
            fail(
                err.get("error", "bookkeeping record failed"),
                exit_code=bk_proc.returncode,
                **{k: v for k, v in err.items() if k != "error"},
            )
        bookkeeping = json.loads(bk_proc.stdout)

        verify_args = [
            sys.executable,
            str(SCRIPT_DIR / "wave_failure.py"),
            str(root),
            "verify",
            "run-after-merge",
            "--phase-slug",
            phase_slug,
        ]
        if orch:
            verify_args.extend(["--orchestrator-worktree", orch])
        verify_proc = subprocess.run(verify_args, cwd=str(root), text=True, capture_output=True)
        if verify_proc.returncode != 0:
            try:
                err = json.loads(verify_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": verify_proc.stderr or verify_proc.stdout}
            fail_payload(
                err,
                "incremental verify failed after merge",
                verify_proc.returncode or 20,
                halt="blocked",
                cause="verify:failed",
            )
        verify_out = json.loads(verify_proc.stdout)

        ack_proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "wave_terminal.py"), str(root), "ack", "record-merge"],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        ack_out = json.loads(ack_proc.stdout) if ack_proc.stdout.strip() else {}

        emit(
            {
                "verdict": "pass",
                "action": "merge-run-next",
                "phase": phase_slug,
                "mergeCommit": merge_commit,
                "remaining": len(state["mergeQueue"]),
                "bookkeeping": bookkeeping,
                "verify": verify_out,
                "ack": ack_out,
                "authPath": auth_path,
            }
        )
    except Exception:
        state = load_state(root)
        state["mergeJournal"] = None
        save_state(root, state)
        raise


def cmd_report_terminal(root: Path, args: list[str]) -> None:
    state = load_state(root)
    target = (state.get("target") or {}).get("branch", "")
    phases = state.get("phases") or {}
    merged_phases = list(state.get("mergedPhases") or [])
    blocked = [p for p in phases.values() if p.get("status") == "blocked"]
    pending = [
        p
        for p in phases.values()
        if p.get("status") not in ("green-merged", "blocked", "rejected")
    ]
    completion = state.get("completion") or {}
    completion_pending = completion.get("status") == "completed-pending-merge"
    all_merged = len(pending) == 0 and len(blocked) == 0 and len(phases) > 0

    phase_prs: list[dict[str, Any]] = []
    for record in merged_phases:
        pr = record.get("pr")
        slug = record.get("phaseSlug")
        url = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'owner/repo')}/pull/{pr}" if pr else None
        phase_prs.append(
            {
                "phaseSlug": slug,
                "pr": pr,
                "prUrl": url,
                "mergeCommit": record.get("mergeCommit"),
            }
        )

    report: dict[str, Any] = {
        "verdict": "complete" if all_merged and not completion_pending else ("blocked" if blocked else "running"),
        "targetBranch": target,
        "phasePrs": phase_prs,
        "blockedPhases": [{"slug": p.get("slug"), "cause": p.get("cause")} for p in blocked],
        "conventionalCommitTypes": ["feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"],
    }
    if completion_pending:
        report["completionPendingMerge"] = True
        report["note"] = (
            "Pre-merge compounding recorded; awaiting human merge — not complete until merged (R53)"
        )
    if all_merged and not state.get("terminalRejected") and not completion_pending:
        report["terminalGate"] = "ready to merge — your call"
        report["note"] = "Open or update single <type>/<slug> → main PR; halt without merging"
        terminal = state.get("terminalPr") or {}
        pr_num = terminal.get("number")
        if pr_num is not None:
            report["terminalPr"] = terminal
            gate_ec, gate = run_check_gate(root, str(pr_num))
            report["gate"] = gate
            report["gateExitCode"] = gate_ec
            if gate_ec == 0 and gate.get("verdict") == "green":
                report["gateVerdict"] = "green"
            else:
                report["gateVerdict"] = gate.get("verdict", "blocked")
    elif state.get("terminalRejected"):
        report["terminalRejected"] = True
        report["note"] = "Terminal PR rejected; resume must not re-present (R46)"
    emit({"verdict": "pass", "action": "report-terminal", "report": report})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_merge.py <root> <domain> <subcommand> [args...]")
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "status":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "collect":
            cmd_status_collect(root, rest)
        else:
            fail("status subcommand required: collect")
    elif domain == "phase":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "dispatch-env":
            cmd_phase_dispatch_env(root, rest)
        else:
            fail("phase subcommand required: dispatch-env")
    elif domain == "merge":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "gate-check":
            cmd_merge_gate_check(root, rest)
        elif sub == "enqueue":
            cmd_merge_enqueue(root, rest)
        elif sub == "exec":
            cmd_merge_exec(root, rest)
        elif sub == "run-next":
            cmd_merge_run_next(root, rest)
        elif sub == "ancestry-check":
            cmd_merge_ancestry_check(root, rest)
        else:
            fail("merge subcommand required: gate-check|enqueue|exec|run-next|ancestry-check")
    elif domain == "report":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "terminal":
            cmd_report_terminal(root, rest)
        else:
            fail("report subcommand required: terminal")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
