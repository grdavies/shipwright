#!/usr/bin/env python3
"""Execute-tier integrate primitive — merge sub-branch tips into phase worktree (PRD 053 R15-R17)."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from _sw.git_integrate import abort_merge, merge_branch_into
from execute_plan import EXECUTE_PLAN_FILENAME, resolve_run_dir, sub_branch_name
from wave_deliver import feature_slug, parse_frontmatter, resolve_task_list_path
from wave_json_io import read_json, write_json
from wave_state import read_lock_meta, reclaim_stale_lock

INTEGRATE_JOURNAL_FILENAME = "integrate-journal.json"
INTEGRATE_LOCK_FILENAME = "integrate.lock"
EXIT_CONFLICT = 20


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def lock_host() -> str:
    return socket.gethostname()


def git_run(args: list[str], cwd: Path, *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        check=check,
    )


def resolve_phase_worktree(root: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).resolve()
        if not path.is_dir():
            fail(f"phase worktree missing: {path}")
        return path
    return root.resolve()


def load_execute_plan(run_dir: Path) -> dict[str, Any]:
    path = run_dir / EXECUTE_PLAN_FILENAME
    if not path.is_file():
        fail(f"missing execute plan: {path}", exit_code=20, cause="integrate:missing-plan")
    return read_json(path, absent_ok=False)


def ref_entry_for_task(plan: dict[str, Any], task_ref: str) -> dict[str, Any]:
    for ref in plan.get("refs") or []:
        if isinstance(ref, dict) and str(ref.get("id")) == task_ref:
            return ref
    fail(f"task ref not in execute plan: {task_ref}", exit_code=20, cause="integrate:unknown-ref")


def resolve_source_ref(
    root: Path,
    plan: dict[str, Any],
    task_ref: str,
    *,
    explicit: str | None,
    phase_slug: str,
    task_list: str | None,
) -> str:
    if explicit:
        return explicit.strip()
    ref = ref_entry_for_task(plan, task_ref)
    branch = str(ref.get("branch") or "").strip()
    if branch:
        return branch
    slug = str(plan.get("phaseSlug") or phase_slug)
    feature = ""
    if task_list:
        content = resolve_task_list_path(root, task_list).read_text(encoding="utf-8")
        fm = parse_frontmatter(content)
        feature = feature_slug(fm.get("topic") or fm.get("prd") or "")
    if not feature:
        feature = feature_slug(slug)
    return sub_branch_name(feature, slug, task_ref)


def journal_path(run_dir: Path) -> Path:
    return run_dir / INTEGRATE_JOURNAL_FILENAME


def load_journal(run_dir: Path) -> dict[str, Any]:
    path = journal_path(run_dir)
    if not path.is_file():
        return {"version": 1, "entries": []}
    data = read_json(path, absent_ok=False)
    entries = data.get("entries")
    if not isinstance(entries, list):
        fail("integrate journal corrupt: entries must be array", exit_code=20, cause="integrate:journal-corrupt")
    return data


def append_journal(run_dir: Path, entry: dict[str, Any]) -> Path:
    journal = load_journal(run_dir)
    entries = journal.setdefault("entries", [])
    if not isinstance(entries, list):
        entries = []
        journal["entries"] = entries
    entries.append({**entry, "at": utc_now()})
    path = journal_path(run_dir)
    write_json(path, journal)
    return path


def latest_journal_entry(run_dir: Path, task_ref: str) -> dict[str, Any] | None:
    journal = load_journal(run_dir)
    matches = [
        entry
        for entry in journal.get("entries") or []
        if isinstance(entry, dict) and str(entry.get("taskRef")) == task_ref
    ]
    return matches[-1] if matches else None


def update_ref_status(run_dir: Path, task_ref: str, status: str, *, merge_commit: str | None = None) -> None:
    plan_path = run_dir / EXECUTE_PLAN_FILENAME
    plan = read_json(plan_path, absent_ok=False)
    updated = False
    for ref in plan.get("refs") or []:
        if isinstance(ref, dict) and str(ref.get("id")) == task_ref:
            ref["status"] = status
            if merge_commit:
                ref["mergeCommit"] = merge_commit
            updated = True
            break
    if not updated:
        fail(f"task ref not in execute plan: {task_ref}", exit_code=20, cause="integrate:unknown-ref")
    write_json(plan_path, plan)


def integrate_lock_path(run_dir: Path) -> Path:
    return run_dir / INTEGRATE_LOCK_FILENAME


@contextmanager
def integrate_lock(run_dir: Path, *, nonblock: bool = False) -> Iterator[None]:
    run_dir.mkdir(parents=True, exist_ok=True)
    lock_path = integrate_lock_path(run_dir)
    now = utc_now()
    meta = {
        "pid": os.getpid(),
        "host": lock_host(),
        "acquiredAt": now,
        "heartbeatAt": now,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    def try_acquire() -> bool:
        try:
            fd = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            return False
        os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
        os.close(fd)
        return True

    if not try_acquire():
        existing = read_lock_meta(lock_path)
        if reclaim_stale_lock(lock_path) and try_acquire():
            pass
        elif nonblock:
            fail(
                "integrate lock held",
                exit_code=EXIT_CONFLICT,
                cause="integrate:lock-held",
                holder=existing,
            )
        else:
            fail(
                "integrate lock held",
                exit_code=EXIT_CONFLICT,
                cause="integrate:lock-held",
                holder=existing,
            )
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def resolve_merge_ref(phase_wt: Path, source_ref: str) -> str:
    if git_run(["show-ref", "--verify", f"refs/heads/{source_ref}"], phase_wt, check=False).returncode == 0:
        return source_ref
    proc = git_run(["rev-parse", "--verify", source_ref], phase_wt, check=False)
    if proc.returncode == 0:
        return source_ref
    fail(f"source ref not found: {source_ref}", exit_code=20, cause="integrate:missing-source")


def cmd_integrate(root: Path, args: argparse.Namespace) -> int:
    phase_wt = resolve_phase_worktree(root, args.phase_worktree)
    run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
    plan = load_execute_plan(run_dir)
    source_ref = resolve_source_ref(
        root,
        plan,
        args.task_ref,
        explicit=args.source_ref,
        phase_slug=args.phase_slug,
        task_list=args.task_list,
    )

    prior = latest_journal_entry(run_dir, args.task_ref)
    if prior and prior.get("verdict") == "pass" and not args.retry:
        emit(
            {
                "verdict": "pass",
                "action": "execute-integrate",
                "taskRef": args.task_ref,
                "phaseSlug": args.phase_slug,
                "note": "already integrated",
                "mergeCommit": prior.get("mergeCommit"),
                "journalPath": str(journal_path(run_dir)),
            }
        )

    merge_ref = resolve_merge_ref(phase_wt, source_ref)
    message = args.message or f"integrate(execute): task {args.task_ref} into phase {args.phase_slug}"

    with integrate_lock(run_dir, nonblock=args.nonblock):
        merge_result = merge_branch_into(phase_wt, merge_ref, message=message, abort_on_conflict=True)
        verdict = str(merge_result.get("verdict") or "fail")
        conflicts = list(merge_result.get("conflicts") or [])
        merge_commit: str | None = None

        if verdict == "pass":
            merge_commit = git_run(["rev-parse", "HEAD"], phase_wt).stdout.strip()
            update_ref_status(run_dir, args.task_ref, "integrated", merge_commit=merge_commit)
            journal_entry = {
                "taskRef": args.task_ref,
                "sourceRef": source_ref,
                "verdict": "pass",
                "mergeCommit": merge_commit,
                "conflicts": [],
                "retry": bool(args.retry),
            }
            path = append_journal(run_dir, journal_entry)
            emit(
                {
                    "verdict": "pass",
                    "action": "execute-integrate",
                    "taskRef": args.task_ref,
                    "phaseSlug": args.phase_slug,
                    "sourceRef": source_ref,
                    "mergeCommit": merge_commit,
                    "journalPath": str(path),
                }
            )

        if verdict == "conflict":
            abort_merge(phase_wt)
            journal_entry = {
                "taskRef": args.task_ref,
                "sourceRef": source_ref,
                "verdict": "conflict",
                "conflicts": conflicts,
                "retry": bool(args.retry),
                "cause": "integrate:conflict",
            }
            path = append_journal(run_dir, journal_entry)
            update_ref_status(run_dir, args.task_ref, "blocked")
            fail(
                "integrate conflict",
                exit_code=EXIT_CONFLICT,
                cause="integrate:conflict",
                taskRef=args.task_ref,
                phaseSlug=args.phase_slug,
                sourceRef=source_ref,
                conflicts=conflicts,
                journalPath=str(path),
                stderr=str(merge_result.get("stderr") or "").strip(),
            )

        abort_merge(phase_wt)
        journal_entry = {
            "taskRef": args.task_ref,
            "sourceRef": source_ref,
            "verdict": "fail",
            "conflicts": conflicts,
            "retry": bool(args.retry),
            "error": str(merge_result.get("error") or merge_result.get("stderr") or "integrate failed"),
        }
        append_journal(run_dir, journal_entry)
        fail(
            str(merge_result.get("error") or "integrate failed"),
            exit_code=EXIT_CONFLICT,
            cause="integrate:fail",
            taskRef=args.task_ref,
            conflicts=conflicts,
        )
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute-tier integrate primitive (PRD 053)")
    sub = parser.add_subparsers(dest="command", required=True)
    integrate = sub.add_parser("integrate")
    integrate.add_argument("--task-ref", required=True)
    integrate.add_argument("--phase-slug", required=True)
    integrate.add_argument("--retry", action="store_true")
    integrate.add_argument("--nonblock", action="store_true")
    integrate.add_argument("--source-ref", default="")
    integrate.add_argument("--phase-worktree", default="")
    integrate.add_argument("--run-dir", default="")
    integrate.add_argument("--task-list", default="")
    integrate.add_argument("--message", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        fail("usage: execute_integrate.py <root> integrate --task-ref REF --phase-slug SLUG")
    root = Path(argv[0])
    args = build_parser().parse_args(argv[1:])
    if args.command == "integrate":
        return cmd_integrate(root, args)
    fail(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
