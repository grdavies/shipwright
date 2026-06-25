#!/usr/bin/env python3
"""Run-state, lock, merge journal, and progress log for /sw-deliver phase-mode."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

VALID_PHASE_STATUSES = frozenset(
    {"pending", "in-flight", "green-merged", "blocked", "rejected"}
)
TERMINAL_VERDICTS = frozenset({"running", "complete", "blocked", "rejected"})


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


def paths(root: Path) -> dict[str, Path]:
    cursor = root / ".cursor"
    runs = cursor / "sw-deliver-runs"
    return {
        "state": cursor / "sw-deliver-state.json",
        "lock": cursor / "sw-deliver.lock",
        "log": runs / "run.log",
        "runs": runs,
    }


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def append_log(root: Path, entry: dict[str, Any]) -> None:
    p = paths(root)
    p["runs"].mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with open(p["log"], "a", encoding="utf-8") as f:
        f.write(line)
    os.chmod(p["log"], 0o600)


def cmd_state_init(root: Path, args: list[str]) -> None:
    plan_path = parse_kv(args, "--plan")
    if not plan_path:
        fail("--plan required")
    plan_file = (root / plan_path).resolve()
    if not plan_file.is_file():
        fail(f"plan not found: {plan_path}")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if plan.get("mode") != "phase":
        fail("state init requires phase-mode plan")

    phases: dict[str, Any] = {}
    for item in plan.get("items") or []:
        pid = str(item.get("id", ""))
        if not pid:
            continue
        phases[pid] = {
            "id": pid,
            "slug": item.get("slug", ""),
            "title": item.get("title", ""),
            "branch": item.get("branch", ""),
            "status": "pending",
            "updatedAt": utc_now(),
        }

    state = {
        "verdict": "running",
        "target": plan.get("target"),
        "source_task_list": plan.get("source_task_list"),
        "prd_number": plan.get("prd_number"),
        "phases": phases,
        "mergeJournal": None,
        "updatedAt": utc_now(),
    }
    write_json(paths(root)["state"], state)
    append_log(
        root,
        {
            "event": "run-init",
            "target": (plan.get("target") or {}).get("branch"),
            "phaseCount": len(phases),
        },
    )
    emit({"verdict": "pass", "action": "state-init", "phaseCount": len(phases)})


def find_phase(state: dict[str, Any], phase_id: str | None, slug: str | None) -> tuple[str, dict[str, Any]]:
    phases = state.get("phases") or {}
    if phase_id:
        if phase_id not in phases:
            fail(f"unknown phase id {phase_id!r}")
        return phase_id, phases[phase_id]
    if slug:
        for pid, meta in phases.items():
            if meta.get("slug") == slug:
                return pid, meta
        fail(f"unknown phase slug {slug!r}")
    fail("--id or --slug required")


def cmd_state_phase(root: Path, args: list[str]) -> None:
    status = parse_kv(args, "--status")
    if not status or status not in VALID_PHASE_STATUSES:
        fail(f"--status required; one of {sorted(VALID_PHASE_STATUSES)}")
    state_path = paths(root)["state"]
    state = read_json(state_path)
    if not state:
        fail("run state missing; run state init first", exit_code=2)

    pid, meta = find_phase(state, parse_kv(args, "--id"), parse_kv(args, "--slug"))
    old_status = meta.get("status")
    state["phases"][pid]["status"] = status
    state["phases"][pid]["updatedAt"] = utc_now()
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(
        root,
        {
            "event": "phase-transition",
            "phaseId": pid,
            "phaseSlug": meta.get("slug"),
            "from": old_status,
            "to": status,
        },
    )
    emit({"verdict": "pass", "action": "state-phase", "phaseId": pid, "status": status})


def cmd_state_get(root: Path, _args: list[str]) -> None:
    state = read_json(paths(root)["state"])
    if not state:
        emit({"verdict": "pass", "state": None, "present": False})
    emit({"verdict": "pass", "present": True, "state": state})


def cmd_state_terminal(root: Path, args: list[str]) -> None:
    verdict = parse_kv(args, "--verdict")
    if not verdict or verdict not in TERMINAL_VERDICTS:
        fail(f"--verdict required; one of {sorted(TERMINAL_VERDICTS)}")
    state_path = paths(root)["state"]
    state = read_json(state_path)
    if not state:
        fail("run state missing")
    state["verdict"] = verdict
    state["updatedAt"] = utc_now()
    cause = parse_kv(args, "--cause")
    if cause:
        state["cause"] = cause
    write_json(state_path, state)
    append_log(root, {"event": "run-terminal", "verdict": verdict, "cause": cause})
    emit({"verdict": "pass", "action": "state-terminal", "runVerdict": verdict})


def cmd_lock_acquire(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if not target:
        fail("--target required (e.g. feat/my-slug)")
    nonblock = "--nonblock" in args
    lock_path = paths(root)["lock"]
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "target": target,
        "pid": os.getpid(),
        "acquiredAt": utc_now(),
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(lock_path, flags, 0o600)
    except FileExistsError:
        existing: dict[str, Any] = {}
        try:
            raw = lock_path.read_text(encoding="utf-8").strip()
            if raw:
                existing = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            pass
        fail("orchestrator lock held", exit_code=20, holder=existing)
    os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
    os.close(fd)
    append_log(root, {"event": "lock-acquire", "target": target})
    emit({"verdict": "pass", "action": "lock-acquire", "target": target})


def cmd_lock_release(root: Path, _args: list[str]) -> None:
    lock_path = paths(root)["lock"]
    if not lock_path.is_file():
        emit({"verdict": "pass", "action": "lock-release", "note": "no lock file"})
    meta: dict[str, Any] = {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw:
            meta = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        pass
    lock_path.unlink(missing_ok=True)
    append_log(root, {"event": "lock-release", "target": meta.get("target")})
    emit({"verdict": "pass", "action": "lock-release"})


def cmd_lock_status(root: Path, _args: list[str]) -> None:
    lock_path = paths(root)["lock"]
    if not lock_path.is_file():
        emit({"verdict": "pass", "held": False})
    meta: dict[str, Any] = {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw:
            meta = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        meta = {}
    emit({"verdict": "pass", "held": True, "lock": meta})


def cmd_journal_begin(root: Path, args: list[str]) -> None:
    slug = parse_kv(args, "--phase")
    if not slug:
        fail("--phase required")
    head = parse_kv(args, "--head", "")
    state_path = paths(root)["state"]
    state = read_json(state_path)
    if not state:
        fail("run state missing")
    if state.get("mergeJournal"):
        fail(
            "merge journal already open",
            exit_code=20,
            journal=state["mergeJournal"],
        )
    journal = {
        "phase": slug,
        "head": head or None,
        "startedAt": utc_now(),
    }
    state["mergeJournal"] = journal
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "merge-begin", "phase": slug, "head": head})
    emit({"verdict": "pass", "action": "journal-begin", "journal": journal})


def cmd_journal_complete(root: Path, args: list[str]) -> None:
    slug = parse_kv(args, "--phase")
    state_path = paths(root)["state"]
    state = read_json(state_path)
    journal = state.get("mergeJournal")
    if not journal:
        fail("no open merge journal")
    if slug and journal.get("phase") != slug:
        fail(f"journal phase mismatch: open={journal.get('phase')!r} requested={slug!r}")
    completed = {**journal, "completedAt": utc_now()}
    state["mergeJournal"] = None
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "merge-complete", "phase": journal.get("phase")})
    emit({"verdict": "pass", "action": "journal-complete", "journal": completed})


def cmd_journal_status(root: Path, _args: list[str]) -> None:
    state = read_json(paths(root)["state"])
    journal = state.get("mergeJournal")
    emit({"verdict": "pass", "open": journal is not None, "journal": journal})


def cmd_log_tail(root: Path, args: list[str]) -> None:
    lines = int(parse_kv(args, "--lines", "10") or "10")
    log_path = paths(root)["log"]
    if not log_path.is_file():
        emit({"verdict": "pass", "entries": []})
    content = log_path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in content[-lines:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    emit({"verdict": "pass", "entries": entries})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_state.py <root> <state|lock|journal|log> <subcommand> [args...]")
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "state":
        if not args:
            fail("state subcommand required: init|get|phase|terminal")
        sub = args[0]
        rest = args[1:]
        if sub == "init":
            cmd_state_init(root, rest)
        elif sub == "get":
            cmd_state_get(root, rest)
        elif sub == "phase":
            cmd_state_phase(root, rest)
        elif sub == "terminal":
            cmd_state_terminal(root, rest)
        else:
            fail(f"unknown state subcommand: {sub}")
    elif domain == "lock":
        if not args:
            fail("lock subcommand required: acquire|release|status")
        sub, rest = args[0], args[1:]
        if sub == "acquire":
            cmd_lock_acquire(root, rest)
        elif sub == "release":
            cmd_lock_release(root, rest)
        elif sub == "status":
            cmd_lock_status(root, rest)
        else:
            fail(f"unknown lock subcommand: {sub}")
    elif domain == "journal":
        if not args:
            fail("journal subcommand required: begin|complete|status")
        sub, rest = args[0], args[1:]
        if sub == "begin":
            cmd_journal_begin(root, rest)
        elif sub == "complete":
            cmd_journal_complete(root, rest)
        elif sub == "status":
            cmd_journal_status(root, rest)
        else:
            fail(f"unknown journal subcommand: {sub}")
    elif domain == "log":
        if not args or args[0] != "tail":
            fail("log subcommand required: tail")
        cmd_log_tail(root, args[1:])
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
