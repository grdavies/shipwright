#!/usr/bin/env python3
"""Run-state, lock, merge journal, and progress log for /sw-deliver phase-mode."""
from __future__ import annotations

import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wave_json_io import StateCorruptError, read_json, write_json

VALID_PHASE_STATUSES = frozenset(
    {"pending", "in-flight", "green-merged", "blocked", "rejected"}
)
TERMINAL_VERDICTS = frozenset({"running", "complete", "blocked", "rejected"})
LOCK_STALE_SECONDS = int(os.environ.get("SW_LOCK_STALE_SECONDS", "3600"))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def assert_phase_status(status: str) -> None:
    if status not in VALID_PHASE_STATUSES:
        fail(
            f"invalid phase status {status!r}; allowed: {sorted(VALID_PHASE_STATUSES)}",
            exit_code=20,
            halt="blocked",
            cause="phase-status:invalid",
        )


def fail_corrupt(path: Path, exc: StateCorruptError) -> None:
    fail(
        f"corrupt durable state: {exc}",
        exit_code=20,
        halt="blocked",
        cause="state:corrupt",
        path=str(path),
    )


def load_state_file(path: Path) -> dict[str, Any]:
    try:
        return read_json(path)
    except StateCorruptError as exc:
        fail_corrupt(path, exc)
        return {}  # unreachable


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


def lock_host() -> str:
    return socket.gethostname()


def lock_is_stale(meta: dict[str, Any]) -> bool:
    ts = meta.get("heartbeatAt") or meta.get("acquiredAt")
    if not isinstance(ts, str):
        return True
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > LOCK_STALE_SECONDS
    except ValueError:
        return True


def lock_owner_live(meta: dict[str, Any]) -> bool:
    """Lock is live when heartbeat is fresh or the recorded pid is still running."""
    if not lock_is_stale(meta):
        return True
    pid = meta.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    return False


def read_lock_meta(lock_path: Path) -> dict[str, Any]:
    if not lock_path.is_file():
        return {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def reclaim_stale_lock(lock_path: Path) -> bool:
    """Remove lock when owner is dead or heartbeat is stale. Returns True if reclaimed."""
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    if lock_owner_live(meta):
        return False
    lock_path.unlink(missing_ok=True)
    return True


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
        "completedMerges": [],
        "currentWave": 1,
        "nextAction": "lock-acquire",
        "remediationAttempts": {},
        "phaseWorktrees": {},
        "driverHeartbeatAt": utc_now(),
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
    if not status:
        fail(f"--status required; one of {sorted(VALID_PHASE_STATUSES)}")
    assert_phase_status(status)
    state_path = paths(root)["state"]
    state = load_state_file(state_path)
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
    state_path = paths(root)["state"]
    if not state_path.is_file():
        emit({"verdict": "pass", "state": None, "present": False})
    state = load_state_file(state_path)
    emit({"verdict": "pass", "present": True, "state": state})


def cmd_state_terminal(root: Path, args: list[str]) -> None:
    verdict = parse_kv(args, "--verdict")
    if not verdict or verdict not in TERMINAL_VERDICTS:
        fail(f"--verdict required; one of {sorted(TERMINAL_VERDICTS)}")
    state_path = paths(root)["state"]
    state = load_state_file(state_path)
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
    now = utc_now()
    meta = {
        "target": target,
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
            append_log(
                root,
                {
                    "event": "lock-reclaim",
                    "target": target,
                    "previousHolder": existing,
                },
            )
        else:
            fail("orchestrator lock held", exit_code=20, holder=existing)
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
    state = load_state_file(state_path)
    if not state:
        fail("run state missing")
    completed = state.get("completedMerges") or []
    merge_key = f"{slug}:{head}" if head else slug
    if any(c.get("key") == merge_key for c in completed if isinstance(c, dict)):
        emit(
            {
                "verdict": "pass",
                "action": "journal-begin",
                "note": "already completed (idempotent)",
                "journal": None,
            }
        )
    open_journal = state.get("mergeJournal")
    if open_journal:
        if open_journal.get("phase") == slug and (
            not head or open_journal.get("head") == head or not open_journal.get("head")
        ):
            emit(
                {
                    "verdict": "pass",
                    "action": "journal-begin",
                    "note": "journal already open (resume)",
                    "journal": open_journal,
                }
            )
        fail(
            "merge journal already open",
            exit_code=20,
            journal=open_journal,
        )
    journal = {
        "phase": slug,
        "head": head or None,
        "startedAt": utc_now(),
        "key": merge_key,
    }
    state["mergeJournal"] = journal
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "merge-begin", "phase": slug, "head": head})
    emit({"verdict": "pass", "action": "journal-begin", "journal": journal})


def cmd_journal_complete(root: Path, args: list[str]) -> None:
    slug = parse_kv(args, "--phase")
    state_path = paths(root)["state"]
    state = load_state_file(state_path)
    journal = state.get("mergeJournal")
    if not journal:
        completed = state.get("completedMerges") or []
        if slug and any(
            isinstance(c, dict) and c.get("phase") == slug for c in completed
        ):
            emit(
                {
                    "verdict": "pass",
                    "action": "journal-complete",
                    "note": "already completed (idempotent)",
                }
            )
        fail("no open merge journal")
    if slug and journal.get("phase") != slug:
        fail(f"journal phase mismatch: open={journal.get('phase')!r} requested={slug!r}")
    completed = {**journal, "completedAt": utc_now()}
    done = list(state.get("completedMerges") or [])
    key = journal.get("key") or journal.get("phase")
    if not any(isinstance(c, dict) and c.get("key") == key for c in done):
        done.append(
            {
                "key": key,
                "phase": journal.get("phase"),
                "head": journal.get("head"),
                "completedAt": completed["completedAt"],
            }
        )
    state["mergeJournal"] = None
    state["completedMerges"] = done
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "merge-complete", "phase": journal.get("phase")})
    emit({"verdict": "pass", "action": "journal-complete", "journal": completed})


def cmd_journal_status(root: Path, _args: list[str]) -> None:
    state = load_state_file(paths(root)["state"])
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


def _task_ledger(state: dict[str, Any]) -> dict[str, Any]:
    ledger = state.get("taskLedger")
    if not isinstance(ledger, dict):
        ledger = {"tasks": {}, "phases": {}}
    ledger.setdefault("tasks", {})
    ledger.setdefault("phases", {})
    return ledger


def cmd_ledger_record(root: Path, args: list[str]) -> None:
    task_ref = parse_kv(args, "--task")
    phase_slug = parse_kv(args, "--phase")
    if not task_ref:
        fail("--task required (e.g. 7.1)")
    done = parse_kv(args, "--done", "true") != "false"
    state_path = paths(root)["state"]
    state = load_state_file(state_path)
    if not state:
        fail("run state missing; run state init first")
    ledger = _task_ledger(state)
    tasks = ledger["tasks"]
    if not isinstance(tasks, dict):
        tasks = {}
        ledger["tasks"] = tasks
    tasks[task_ref] = {
        "done": done,
        "phase": phase_slug,
        "updatedAt": utc_now(),
    }
    if phase_slug:
        phases = ledger["phases"]
        if isinstance(phases, dict):
            phases.setdefault(phase_slug, {"tasks": [], "updatedAt": utc_now()})
            phase_entry = phases[phase_slug]
            if isinstance(phase_entry, dict):
                refs = phase_entry.setdefault("tasks", [])
                if isinstance(refs, list) and task_ref not in refs:
                    refs.append(task_ref)
                phase_entry["updatedAt"] = utc_now()
    state["taskLedger"] = ledger
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "ledger-record", "task": task_ref, "done": done, "phase": phase_slug})
    emit({"verdict": "pass", "action": "ledger-record", "task": task_ref, "done": done})


def cmd_ledger_check(root: Path, args: list[str]) -> None:
    tasks_file = parse_kv(args, "--tasks-file")
    if not tasks_file:
        fail("--tasks-file required")
    path = (root / tasks_file).resolve() if not Path(tasks_file).is_absolute() else Path(tasks_file)
    if not path.is_file():
        fail(f"tasks file not found: {tasks_file}")
    state_path = paths(root)["state"]
    state = load_state_file(state_path) if state_path.is_file() else {}
    ledger_tasks = ((state.get("taskLedger") or {}).get("tasks") or {}) if state else {}

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from checkbox_diff import parse_task_checkboxes

    checkboxes = parse_task_checkboxes(path.read_text(encoding="utf-8"))
    divergences: list[dict[str, Any]] = []

    for ref, checked in checkboxes.items():
        entry = ledger_tasks.get(ref) if isinstance(ledger_tasks, dict) else None
        if not entry:
            if checked:
                divergences.append(
                    {"ref": ref, "kind": "stale", "reason": "checkbox-checked-missing-ledger"}
                )
            continue
        ledger_done = bool(entry.get("done"))
        if ledger_done != checked:
            divergences.append(
                {
                    "ref": ref,
                    "kind": "divergence",
                    "reason": "checkbox-ledger-mismatch",
                    "checkbox": checked,
                    "ledger": ledger_done,
                }
            )

    if isinstance(ledger_tasks, dict):
        for ref, entry in ledger_tasks.items():
            if not isinstance(entry, dict) or not entry.get("done"):
                continue
            if not checkboxes.get(ref, False):
                if not any(d.get("ref") == ref for d in divergences):
                    divergences.append(
                        {"ref": ref, "kind": "stale", "reason": "ledger-done-checkbox-open"}
                    )

    if divergences:
        emit(
            {
                "verdict": "fail",
                "error": "task currency divergence",
                "divergences": divergences,
                "partial": any(d.get("kind") == "stale" for d in divergences),
            },
            exit_code=1,
        )
    emit({"verdict": "pass", "action": "ledger-check", "taskCount": len(checkboxes)})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_state.py <root> <state|lock|journal|log|ledger> <subcommand> [args...]")
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
    elif domain == "ledger":
        if not args:
            fail("ledger subcommand required: record|check")
        sub, rest = args[0], args[1:]
        if sub == "record":
            cmd_ledger_record(root, rest)
        elif sub == "check":
            cmd_ledger_check(root, rest)
        else:
            fail(f"unknown ledger subcommand: {sub}")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
