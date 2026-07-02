#!/usr/bin/env python3
"""Bounded loop auto-propose driver — draft-only handoffs (PRD 041 R27/R30)."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import socket
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp
from planning_autonomy import FORBIDDEN_ORCHESTRATORS
from wave_json_io import read_json, write_json

STATE_REL = Path(".cursor/hooks/state/loop-autonomy.json")
ALLOWED_HANDOFF_PREFIXES = (
    "python3 scripts/planning_gap_capture.py",
    "python3 scripts/planning-graph.py reconcile",
    "/sw-prd --draft",
)
WRAPPER_MARKERS = ("bash -c", "sh -c", "env ")
META_GAP_CLASSES = frozenset({"plugin-self"})
META_DESTINATIONS = frozenset({"meta-shipwright"})
NESTED_DISPATCH_EXIT = 32
WRAPPER_EXIT = 34
DOC_AFTER_TASKS_EXIT = 35
RUNAWAY_EXIT = 36
CONFIRM_EXIT = 30
DOC_AFTER_TASKS_RE = re.compile(r"doc\.aftertasks\s*:\s*auto", re.I)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def actor_id() -> str:
    return os.environ.get("SW_RECOVERY_ACTOR") or f"{getpass.getuser()}@{socket.gethostname()}"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def state_path(root: Path) -> Path:
    return pp.git_root(root) / STATE_REL


def load_state(root: Path) -> dict[str, Any]:
    path = state_path(root)
    if not path.is_file():
        return {
            "sessionId": str(uuid.uuid4()),
            "proposalLog": [],
            "handoffQueue": [],
            "proposalsToday": 0,
            "dayKey": utc_now()[:10],
            "lastProposalAt": None,
            "halted": False,
        }
    data = read_json(path)
    if not isinstance(data, dict):
        return load_state(root)
    data.setdefault("sessionId", str(uuid.uuid4()))
    data.setdefault("proposalLog", [])
    data.setdefault("handoffQueue", [])
    data.setdefault("proposalsToday", 0)
    data.setdefault("dayKey", utc_now()[:10])
    data.setdefault("lastProposalAt", None)
    data.setdefault("halted", False)
    return data


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)


def auto_propose_config(root: Path) -> dict[str, Any]:
    cfg = pp.load_workflow_config(root)
    block = cfg.get("loop") if isinstance(cfg.get("loop"), dict) else {}
    ap = block.get("autoPropose") if isinstance(block.get("autoPropose"), dict) else {}
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    scheduler = str(ap.get("scheduler") or "manual").strip().lower()
    if scheduler not in ("manual", "scheduled"):
        scheduler = "manual"
    max_per_day = ap.get("maxPerDay")
    if not isinstance(max_per_day, int) or max_per_day < 1:
        max_per_day = 5
    dedup = ap.get("dedupWindow")
    if not isinstance(dedup, int) or dedup < 0:
        dedup = 3600
    cooldown = ap.get("cooldownMinutes")
    if not isinstance(cooldown, int) or cooldown < 0:
        cooldown = 30
    max_open = ap.get("maxOpenMetaUnits")
    if not isinstance(max_open, int) or max_open < 1:
        max_open = 10
    return {
        "enabled": ap.get("enabled") is True,
        "maxPerDay": max_per_day,
        "dedupWindow": dedup,
        "cooldownMinutes": cooldown,
        "maxOpenMetaUnits": max_open,
        "scheduler": scheduler,
        "planningAutonomy": planning.get("autonomy") or "maintenance-only",
    }


def is_meta_unit(*, gap_class: str | None = None, destination: str | None = None) -> bool:
    if (gap_class or "").strip().lower() in META_GAP_CLASSES:
        return True
    if (destination or "").strip().lower() in META_DESTINATIONS:
        return True
    return False


def check_wrapper_indirection(command: str) -> dict[str, Any]:
    normalized = command.strip()
    lower = normalized.lower()
    for marker in WRAPPER_MARKERS:
        if lower.startswith(marker) or f" {marker}" in lower:
            return {"wrapper": True, "marker": marker, "command": command}
    return {"wrapper": False, "command": command}


def check_doc_after_tasks_auto(command: str) -> dict[str, Any]:
    if DOC_AFTER_TASKS_RE.search(command):
        return {"forbidden": True, "reason": "doc.afterTasks:auto", "command": command}
    if "aftertasks" in command.lower() and "auto" in command.lower() and "sw-deliver" in command.lower():
        return {"forbidden": True, "reason": "doc.afterTasks:auto", "command": command}
    return {"forbidden": False, "command": command}


def command_has_allowed_prefix(command: str) -> bool:
    stripped = command.strip()
    lower = stripped.lower()
    for prefix in ALLOWED_HANDOFF_PREFIXES:
        if lower.startswith(prefix.lower()):
            if prefix.lower().startswith("/sw-prd"):
                return "--draft" in lower
            return True
    return False


def check_nested_dispatch(command: str) -> dict[str, Any]:
    wrapper = check_wrapper_indirection(command)
    if wrapper.get("wrapper"):
        return {"forbidden": True, "reason": "wrapper-indirection", **wrapper}
    doc_auto = check_doc_after_tasks_auto(command)
    if doc_auto.get("forbidden"):
        return {"forbidden": True, **doc_auto}
    normalized = command.strip().lower()
    for token in FORBIDDEN_ORCHESTRATORS:
        if token in normalized:
            return {"forbidden": True, "orchestrator": token, "command": command}
    allowed = command_has_allowed_prefix(command)
    return {"forbidden": False, "allowedHandoff": allowed, "command": command}


def count_open_meta_units(root: Path) -> int:
    inbox = pp.git_root(root) / ".cursor" / "sw-meta-inbox"
    if not inbox.is_dir():
        return 0
    count = 0
    for path in inbox.glob("*.json"):
        try:
            draft = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(draft, dict):
            continue
        if draft.get("status") == "draft" and draft.get("destination") == "meta-shipwright":
            count += 1
    return count


def _roll_daily_counter(state: dict[str, Any]) -> None:
    today = utc_now()[:10]
    if state.get("dayKey") != today:
        state["dayKey"] = today
        state["proposalsToday"] = 0


def check_runaway(root: Path, *, signal_id: str | None = None) -> dict[str, Any]:
    cfg = auto_propose_config(root)
    state = load_state(root)
    _roll_daily_counter(state)
    save_state(root, state)
    now = datetime.now(timezone.utc)
    reasons: list[str] = []
    if state.get("halted"):
        reasons.append("driver-halted")
    if int(state.get("proposalsToday") or 0) >= cfg["maxPerDay"]:
        reasons.append("max-per-day")
    open_meta = count_open_meta_units(root)
    if open_meta >= cfg["maxOpenMetaUnits"]:
        reasons.append("max-open-meta-units")
    last = state.get("lastProposalAt")
    if isinstance(last, str):
        ts = parse_ts(last)
        if ts and (now - ts) < timedelta(minutes=cfg["cooldownMinutes"]):
            reasons.append("cooldown")
    if signal_id and cfg["dedupWindow"] > 0:
        for entry in state.get("proposalLog") or []:
            if not isinstance(entry, dict):
                continue
            if entry.get("signalId") != signal_id:
                continue
            ts = parse_ts(str(entry.get("proposedAt", "")))
            if ts and (now - ts).total_seconds() < cfg["dedupWindow"]:
                reasons.append("dedup-window")
                break
    return {
        "exhausted": bool(reasons),
        "reasons": reasons,
        "proposalsToday": int(state.get("proposalsToday") or 0),
        "maxPerDay": cfg["maxPerDay"],
        "openMetaUnits": open_meta,
        "maxOpenMetaUnits": cfg["maxOpenMetaUnits"],
    }


def evaluate_candidate(
    root: Path,
    *,
    gap_class: str | None = None,
    destination: str | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    cfg = auto_propose_config(root)
    if scheduled or cfg["scheduler"] == "scheduled":
        if cfg["planningAutonomy"] == "full-conductor":
            return {
                "verdict": "refuse",
                "posture": "maintenance-only",
                "requiresConfirm": True,
                "message": "scheduled loop auto-propose is maintenance-only",
            }
    if not cfg["enabled"]:
        return {
            "verdict": "propose",
            "eligibleAuto": False,
            "requiresConfirm": True,
            "message": "loop.autoPropose disabled — draft proposal only",
        }
    if is_meta_unit(gap_class=gap_class, destination=destination):
        return {
            "verdict": "propose",
            "eligibleAuto": False,
            "requiresConfirm": True,
            "message": "meta-shipwright / plugin-self is propose-only (never eligible-auto)",
        }
    return {
        "verdict": "propose",
        "eligibleAuto": False,
        "requiresConfirm": True,
        "message": "loop auto-propose is draft-only; human ack required to execute handoffs",
    }


def enqueue_handoff(root: Path, command: str, *, reason: str, signal_id: str | None = None) -> dict[str, Any]:
    cmd = command.strip()
    if not cmd:
        fail("handoff command required")
    nested = check_nested_dispatch(cmd)
    if nested.get("forbidden"):
        code = NESTED_DISPATCH_EXIT
        if nested.get("reason") == "wrapper-indirection":
            code = WRAPPER_EXIT
        if nested.get("reason") == "doc.afterTasks:auto":
            code = DOC_AFTER_TASKS_EXIT
        fail("handoff command forbidden for loop auto-propose", exit_code=code, **nested)
    if not nested.get("allowedHandoff"):
        fail(
            "handoff command not on closed allowlist",
            exit_code=NESTED_DISPATCH_EXIT,
            **nested,
        )
    state = load_state(root)
    entry = {
        "command": cmd,
        "reason": reason,
        "signalId": signal_id,
        "enqueuedAt": utc_now(),
        "inert": True,
        "requiresHumanAck": True,
        "executed": False,
    }
    queue = state.get("handoffQueue") or []
    if not isinstance(queue, list):
        queue = []
    queue.append(entry)
    state["handoffQueue"] = queue
    save_state(root, state)
    return {"verdict": "enqueued", "handoff": entry, "queueLength": len(queue), "inert": True}


def propose(
    root: Path,
    *,
    signal_id: str,
    title: str,
    gap_class: str = "plugin-self",
    destination: str = "meta-shipwright",
    handoff_command: str | None = None,
    scheduled: bool = False,
) -> dict[str, Any]:
    cfg = auto_propose_config(root)
    if not cfg["enabled"]:
        fail("loop.autoPropose.enabled is false")
    runaway = check_runaway(root, signal_id=signal_id)
    if runaway["exhausted"]:
        state = load_state(root)
        state["halted"] = True
        save_state(root, state)
        fail(
            "runaway containment tripped",
            exit_code=RUNAWAY_EXIT,
            halt="loop-auto-propose-runaway",
            **runaway,
        )
    evaluation = evaluate_candidate(
        root,
        gap_class=gap_class,
        destination=destination,
        scheduled=scheduled,
    )
    if evaluation.get("verdict") == "refuse":
        fail("scheduled substrate refuses full-conductor", **evaluation)
    state = load_state(root)
    _roll_daily_counter(state)
    record = {
        "signalId": signal_id,
        "title": title,
        "gapClass": gap_class,
        "destination": destination,
        "proposedAt": utc_now(),
        "proposedBy": actor_id(),
        "evaluation": evaluation,
        "draftOnly": True,
    }
    log = state.get("proposalLog") or []
    if not isinstance(log, list):
        log = []
    log.append(record)
    state["proposalLog"] = log[-200:]
    state["proposalsToday"] = int(state.get("proposalsToday") or 0) + 1
    state["lastProposalAt"] = record["proposedAt"]
    save_state(root, state)
    handoff = None
    if handoff_command:
        handoff = enqueue_handoff(root, handoff_command, reason=f"proposal {signal_id}", signal_id=signal_id)
    return {
        "verdict": "proposed",
        "proposal": record,
        "handoff": handoff,
        "evaluation": evaluation,
        "runaway": check_runaway(root),
    }


def driver_step(root: Path, *, proposals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    cfg = auto_propose_config(root)
    state = load_state(root)
    if state.get("halted"):
        fail("loop auto-propose halted", halt="loop-auto-propose-runaway")
    if cfg["scheduler"] == "scheduled" and cfg["planningAutonomy"] == "full-conductor":
        fail("scheduled runs are maintenance-only only", posture="maintenance-only")
    results: list[dict[str, Any]] = []
    for item in proposals or []:
        if not isinstance(item, dict):
            continue
        signal_id = str(item.get("signalId") or item.get("id") or "")
        if not signal_id:
            continue
        try:
            out = propose(
                root,
                signal_id=signal_id,
                title=str(item.get("title") or signal_id),
                gap_class=str(item.get("gapClass") or "plugin-self"),
                destination=str(item.get("destination") or "meta-shipwright"),
                handoff_command=item.get("handoffCommand"),
                scheduled=cfg["scheduler"] == "scheduled",
            )
            results.append(out)
        except SystemExit:
            raise
        except Exception as exc:
            results.append({"signalId": signal_id, "verdict": "fail", "error": str(exc)})
    return {
        "verdict": "step-complete",
        "scheduler": cfg["scheduler"],
        "results": results,
        "budget": check_runaway(root),
        "handoffQueue": load_state(root).get("handoffQueue") or [],
    }


def cmd_posture(root: Path, _args: argparse.Namespace) -> int:
    emit({"verdict": "ok", "autoPropose": auto_propose_config(root)})
    return 0


def cmd_evaluate(root: Path, args: argparse.Namespace) -> int:
    result = evaluate_candidate(
        root,
        gap_class=args.gap_class,
        destination=args.destination,
        scheduled=args.scheduled,
    )
    exit_code = CONFIRM_EXIT if result.get("requiresConfirm") else 0
    if result.get("verdict") == "refuse":
        exit_code = RUNAWAY_EXIT
    emit({"verdict": "ok", "evaluation": result}, exit_code)
    return 0


def cmd_enqueue(root: Path, args: argparse.Namespace) -> int:
    emit(enqueue_handoff(root, args.command, reason=args.reason or "handoff", signal_id=args.signal_id))
    return 0


def cmd_check_dispatch(root: Path, args: argparse.Namespace) -> int:
    result = check_nested_dispatch(args.command)
    if result.get("forbidden"):
        code = NESTED_DISPATCH_EXIT
        if result.get("reason") == "wrapper-indirection":
            code = WRAPPER_EXIT
        if result.get("reason") == "doc.afterTasks:auto":
            code = DOC_AFTER_TASKS_EXIT
        fail("dispatch forbidden", exit_code=code, **result)
    if not result.get("allowedHandoff"):
        fail("not on allowlist", exit_code=NESTED_DISPATCH_EXIT, **result)
    emit({"verdict": "ok", **result})
    return 0


def cmd_check_runaway(root: Path, args: argparse.Namespace) -> int:
    out = check_runaway(root, signal_id=args.signal_id)
    if out.get("exhausted") and args.fail_on_exhausted:
        fail("runaway containment", exit_code=RUNAWAY_EXIT, **out)
    emit({"verdict": "ok", **out})
    return 0


def cmd_propose(root: Path, args: argparse.Namespace) -> int:
    emit(
        propose(
            root,
            signal_id=args.signal_id,
            title=args.title,
            gap_class=args.gap_class,
            destination=args.destination,
            handoff_command=args.handoff_command,
            scheduled=args.scheduled,
        )
    )
    return 0


def cmd_step(root: Path, args: argparse.Namespace) -> int:
    proposals = None
    if args.proposals_file:
        data = json.loads(Path(args.proposals_file).read_text(encoding="utf-8"))
        proposals = data if isinstance(data, list) else data.get("proposals")
    emit(driver_step(root, proposals=proposals))
    return 0


def cmd_budget(root: Path, _args: argparse.Namespace) -> int:
    cfg = auto_propose_config(root)
    runaway = check_runaway(root)
    emit(
        {
            "verdict": "ok",
            "maxPerDay": cfg["maxPerDay"],
            "proposalsToday": runaway["proposalsToday"],
            "remaining": max(0, cfg["maxPerDay"] - runaway["proposalsToday"]),
            "openMetaUnits": runaway["openMetaUnits"],
            "maxOpenMetaUnits": cfg["maxOpenMetaUnits"],
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PRD 041 loop auto-propose driver (draft-only)")
    parser.add_argument("root", nargs="?", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("posture").set_defaults(func=cmd_posture)

    p_eval = sub.add_parser("evaluate")
    p_eval.add_argument("--gap-class", default="plugin-self")
    p_eval.add_argument("--destination", default="meta-shipwright")
    p_eval.add_argument("--scheduled", action="store_true")
    p_eval.set_defaults(func=cmd_evaluate)

    p_enqueue = sub.add_parser("enqueue-handoff")
    p_enqueue.add_argument("--command", required=True)
    p_enqueue.add_argument("--reason", default="")
    p_enqueue.add_argument("--signal-id", default=None)
    p_enqueue.set_defaults(func=cmd_enqueue)

    p_check = sub.add_parser("check-dispatch")
    p_check.add_argument("--command", required=True)
    p_check.set_defaults(func=cmd_check_dispatch)

    p_run = sub.add_parser("check-runaway")
    p_run.add_argument("--signal-id", default=None)
    p_run.add_argument("--fail-on-exhausted", action="store_true")
    p_run.set_defaults(func=cmd_check_runaway)

    p_prop = sub.add_parser("propose")
    p_prop.add_argument("--signal-id", required=True)
    p_prop.add_argument("--title", required=True)
    p_prop.add_argument("--gap-class", default="plugin-self")
    p_prop.add_argument("--destination", default="meta-shipwright")
    p_prop.add_argument("--handoff-command", default=None)
    p_prop.add_argument("--scheduled", action="store_true")
    p_prop.set_defaults(func=cmd_propose)

    sub.add_parser("budget").set_defaults(func=cmd_budget)

    p_step = sub.add_parser("step")
    p_step.add_argument("--proposals-file")
    p_step.set_defaults(func=cmd_step)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    return int(args.func(root, args))


if __name__ == "__main__":
    raise SystemExit(main())
