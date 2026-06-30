#!/usr/bin/env python3
"""Planning autonomy posture + bounded full-conductor driver (PRD 035 R6-R9, R19, R23)."""
from __future__ import annotations

import argparse
import getpass
import json
import os
import socket
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths as pp
from wave_json_io import read_json, write_json

STATE_REL = Path(".cursor/hooks/state/planning-autonomy.json")
AUTONOMY_VALUES = frozenset({"maintenance-only", "full-conductor"})
MECHANICAL_DECISIONS = frozenset(
    {
        "reconcile",
        "reconcile-batch",
        "index-derived",
        "edge-status-sync",
        "superseded-manifest",
        "gap-index",
        "gap-schedule-sync",
        "bookkeeping",
        "graph-bookkeeping",
        "graph-bookkeeping",
    }
)
CONTENT_DECISIONS = frozenset(
    {
        "pull-in",
        "amendment",
        "priority-change",
        "cancel",
        "supersede",
        "content-authoring",
    }
)
GAP_ABSORPTION_DECISIONS = frozenset({"gap-absorb", "absorb-edge", "absorption"})
PRIVATE_VISIBILITIES = frozenset({"private", "memory"})
FORBIDDEN_ORCHESTRATORS = frozenset(
    {
        "sw-deliver",
        "sw-doc",
        "sw-ship",
        "sw-debug",
        "sw-feedback",
        "sw-cleanup",
        "sw-retrospective",
        "sw-deliver run",
        "sw-doc ",
    }
)
ALLOWED_HANDOFF_PREFIXES = (
    "/sw-prd",
    "/sw-tasks",
    "/sw-amend",
    "bash scripts/planning-graph.sh reconcile",
    "python3 scripts/planning-related.py",
)
BUDGET_HALT_EXIT = 31
NESTED_DISPATCH_EXIT = 32
PRIVATE_REFUSAL_EXIT = 33
CONFIRM_EXIT = 30


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
            "mutationCount": 0,
            "pendingUndo": [],
            "actionLog": [],
            "halted": False,
            "handoffQueue": [],
            "reconcileBatchComplete": False,
        }
    data = read_json(path)
    if not isinstance(data, dict):
        return load_state(root)
    data.setdefault("sessionId", str(uuid.uuid4()))
    data.setdefault("mutationCount", 0)
    data.setdefault("pendingUndo", [])
    data.setdefault("actionLog", [])
    data.setdefault("halted", False)
    data.setdefault("handoffQueue", [])
    data.setdefault("reconcileBatchComplete", False)
    return data


def save_state(root: Path, state: dict[str, Any]) -> None:
    path = state_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)


def posture_config(root: Path) -> dict[str, Any]:
    cfg = pp.load_workflow_config(root)
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    raw = planning.get("autonomy")
    mode = str(raw) if raw in AUTONOMY_VALUES else "maintenance-only"
    fc = planning.get("fullConductor") if isinstance(planning.get("fullConductor"), dict) else {}
    threshold = fc.get("confidenceThreshold")
    if not isinstance(threshold, (int, float)):
        threshold = 0.85
    budget = fc.get("mutationBudget")
    if not isinstance(budget, int) or budget < 1:
        budget = 10
    undo = fc.get("undoWindowSeconds")
    if not isinstance(undo, int) or undo < 0:
        undo = 300
    return {
        "mode": mode,
        "confidenceThreshold": float(threshold),
        "mutationBudget": int(budget),
        "undoWindowSeconds": int(undo),
    }


def classify_decision(decision_type: str) -> str:
    normalized = decision_type.strip().lower().replace("_", "-")
    if normalized in MECHANICAL_DECISIONS:
        return "mechanical"
    if normalized in GAP_ABSORPTION_DECISIONS:
        return "gap-absorption"
    if normalized in CONTENT_DECISIONS:
        return "content"
    if normalized.startswith("gap"):
        return "gap-absorption"
    return "content"


def is_private_unit(visibility: str | None, unit_type: str | None = None) -> bool:
    vis = (visibility or "").strip().lower()
    if vis in PRIVATE_VISIBILITIES:
        return True
    if (unit_type or "").strip().lower() == "memory":
        return True
    return False


def evaluate_decision(
    root: Path,
    *,
    decision_type: str,
    visibility: str | None = None,
    unit_type: str | None = None,
) -> dict[str, Any]:
    posture = posture_config(root)
    decision_class = classify_decision(decision_type)
    if decision_class == "mechanical":
        return {
            "verdict": "autonomous",
            "posture": posture["mode"],
            "decisionClass": decision_class,
            "requiresPrompt": False,
            "requiresConfirm": False,
        }
    if posture["mode"] == "maintenance-only":
        return {
            "verdict": "propose",
            "posture": posture["mode"],
            "decisionClass": decision_class,
            "requiresPrompt": False,
            "requiresConfirm": True,
            "message": "content decision auto-proposed; human confirmation required",
        }
    if decision_class != "gap-absorption":
        return {
            "verdict": "propose",
            "posture": posture["mode"],
            "decisionClass": decision_class,
            "requiresPrompt": False,
            "requiresConfirm": True,
            "message": "full-conductor elevates gap/absorption only; content decision remains gated",
        }
    if is_private_unit(visibility, unit_type):
        return {
            "verdict": "refuse",
            "posture": posture["mode"],
            "decisionClass": decision_class,
            "requiresConfirm": True,
            "reason": "private-or-memory-unit",
        }
    return {
        "verdict": "eligible-auto",
        "posture": posture["mode"],
        "decisionClass": decision_class,
        "requiresConfirm": False,
        "confidenceThreshold": posture["confidenceThreshold"],
        "undoWindowSeconds": posture["undoWindowSeconds"],
    }


def log_autonomy_action(
    root: Path,
    *,
    kind: str,
    why: str,
    extra: dict[str, Any] | None = None,
    who: str | None = None,
) -> dict[str, Any]:
    state = load_state(root)
    entry = {
        "kind": kind,
        "who": who or actor_id(),
        "when": utc_now(),
        "why": why,
        **(extra or {}),
    }
    log = state.get("actionLog") or []
    if not isinstance(log, list):
        log = []
    log.append(entry)
    state["actionLog"] = log[-100:]
    save_state(root, state)
    proc = subprocess.run(
        ["bash", str(SCRIPT_DIR / "shipwright-state.py"), "override-add", json.dumps(entry)],
        cwd=str(pp.git_root(root)),
        capture_output=True,
        text=True,
    )
    return {"logged": True, "entry": entry, "shipwrightState": proc.returncode == 0}


def check_mutation_budget(root: Path) -> dict[str, Any]:
    posture = posture_config(root)
    state = load_state(root)
    count = int(state.get("mutationCount") or 0)
    budget = posture["mutationBudget"]
    remaining = max(0, budget - count)
    return {
        "mutationCount": count,
        "mutationBudget": budget,
        "remaining": remaining,
        "exhausted": count >= budget,
        "halt": "planning-mutation-budget" if count >= budget else None,
    }


def check_nested_dispatch(command: str) -> dict[str, Any]:
    normalized = command.strip().lower()
    for token in FORBIDDEN_ORCHESTRATORS:
        if token in normalized:
            return {"forbidden": True, "orchestrator": token, "command": command}
    allowed = any(normalized.startswith(prefix.lower()) for prefix in ALLOWED_HANDOFF_PREFIXES)
    return {"forbidden": False, "allowedHandoff": allowed, "command": command}


def enqueue_handoff(root: Path, command: str, *, reason: str) -> dict[str, Any]:
    cmd = command.strip()
    if not cmd:
        fail("handoff command required")
    nested = check_nested_dispatch(cmd)
    if nested.get("forbidden"):
        fail(
            "orchestrator nested dispatch forbidden for planning full-conductor",
            exit_code=NESTED_DISPATCH_EXIT,
            **nested,
        )
    state = load_state(root)
    if not state.get("reconcileBatchComplete"):
        fail(
            "halt between reconcile batch and downstream dispatch",
            halt="reconcile-dispatch-boundary",
            exit_code=NESTED_DISPATCH_EXIT,
        )
    entry = {"command": cmd, "reason": reason, "enqueuedAt": utc_now()}
    queue = state.get("handoffQueue") or []
    if not isinstance(queue, list):
        queue = []
    queue.append(entry)
    state["handoffQueue"] = queue
    state["reconcileBatchComplete"] = False
    save_state(root, state)
    return {"verdict": "enqueued", "handoff": entry, "queueLength": len(queue)}


def auto_decide_proposal(
    root: Path,
    *,
    candidate_id: str,
    decision_type: str,
    confidence: float,
    visibility: str | None = None,
    unit_type: str | None = None,
    source_unit: str | None = None,
) -> dict[str, Any]:
    posture = posture_config(root)
    if posture["mode"] != "full-conductor":
        fail("auto-decide requires planning.autonomy full-conductor", posture=posture["mode"])
    evaluation = evaluate_decision(root, decision_type=decision_type, visibility=visibility, unit_type=unit_type)
    if evaluation.get("verdict") == "refuse":
        fail(
            "never auto-absorb private/memory units",
            exit_code=PRIVATE_REFUSAL_EXIT,
            candidateId=candidate_id,
            **evaluation,
        )
    if evaluation.get("verdict") != "eligible-auto":
        fail("decision not eligible for auto-decide", candidateId=candidate_id, **evaluation)
    budget = check_mutation_budget(root)
    if budget["exhausted"]:
        fail(
            "per-session mutation budget exhausted; halt for human resume",
            exit_code=BUDGET_HALT_EXIT,
            halt="planning-mutation-budget",
            mutationCount=budget["mutationCount"],
            mutationBudget=budget["mutationBudget"],
            remaining=budget["remaining"],
            exhausted=budget["exhausted"],
        )
    if confidence < posture["confidenceThreshold"]:
        fail(
            "confidence below threshold",
            candidateId=candidate_id,
            confidence=confidence,
            threshold=posture["confidenceThreshold"],
        )
    state = load_state(root)
    undo_expires = (
        datetime.now(timezone.utc) + timedelta(seconds=posture["undoWindowSeconds"])
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    pending = state.get("pendingUndo") or []
    if not isinstance(pending, list):
        pending = []
    record = {
        "candidateId": candidate_id,
        "sourceUnit": source_unit,
        "decisionType": decision_type,
        "confidence": confidence,
        "decidedAt": utc_now(),
        "undoExpiresAt": undo_expires,
        "materialized": False,
    }
    pending.append(record)
    state["pendingUndo"] = pending
    state["mutationCount"] = int(state.get("mutationCount") or 0) + 1
    save_state(root, state)
    log_autonomy_action(
        root,
        kind="full-conductor-auto-decide",
        why=f"gap/absorption auto-decide {candidate_id}",
        extra={"candidateId": candidate_id, "confidence": confidence, "undoExpiresAt": undo_expires},
    )
    return {
        "verdict": "auto-decided",
        "candidateId": candidate_id,
        "undoExpiresAt": undo_expires,
        "mutationCount": state["mutationCount"],
        "mutationBudget": posture["mutationBudget"],
        "materializeAfterUndoWindow": True,
    }


def materialize_ready(root: Path) -> dict[str, Any]:
    state = load_state(root)
    now = datetime.now(timezone.utc)
    pending = state.get("pendingUndo") or []
    if not isinstance(pending, list):
        pending = []
    ready: list[dict[str, Any]] = []
    still_pending: list[dict[str, Any]] = []
    for item in pending:
        if not isinstance(item, dict):
            continue
        if item.get("materialized"):
            continue
        expires = parse_ts(str(item.get("undoExpiresAt", "")))
        if expires and now >= expires:
            item = {**item, "materialized": True, "materializedAt": utc_now()}
            ready.append(item)
        else:
            still_pending.append(item)
    state["pendingUndo"] = still_pending + [r for r in ready if r.get("materialized")]
    save_state(root, state)
    return {"verdict": "ok", "ready": ready, "pending": len(still_pending)}


def mark_reconcile_complete(root: Path) -> dict[str, Any]:
    state = load_state(root)
    state["reconcileBatchComplete"] = True
    save_state(root, state)
    return {"verdict": "ok", "reconcileBatchComplete": True}


def reset_dispatch_boundary(root: Path) -> dict[str, Any]:
    state = load_state(root)
    state["reconcileBatchComplete"] = False
    state["handoffQueue"] = []
    save_state(root, state)
    return {"verdict": "ok", "reconcileBatchComplete": False}


def driver_step(root: Path, *, proposals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    posture = posture_config(root)
    state = load_state(root)
    if state.get("halted"):
        fail("driver halted; human resume required", halt="planning-mutation-budget", posture=posture["mode"])
    results: list[dict[str, Any]] = []
    handoffs: list[dict[str, Any]] = []
    for proposal in proposals or []:
        if not isinstance(proposal, dict):
            continue
        candidate_id = str(proposal.get("candidateId") or proposal.get("id") or "")
        decision_type = str(proposal.get("decisionType") or proposal.get("route") or "gap-absorb")
        confidence = float(proposal.get("confidence") or proposal.get("score") or 0)
        visibility = proposal.get("visibility")
        unit_type = proposal.get("type") or proposal.get("candidateType")
        evaluation = evaluate_decision(root, decision_type=decision_type, visibility=visibility, unit_type=unit_type)
        if evaluation.get("verdict") == "refuse":
            results.append({"candidateId": candidate_id, "verdict": "refuse", **evaluation})
            continue
        if posture["mode"] == "maintenance-only" or evaluation.get("verdict") != "eligible-auto":
            results.append({"candidateId": candidate_id, "verdict": "propose", **evaluation})
            continue
        decided = auto_decide_proposal(
            root,
            candidate_id=candidate_id,
            decision_type=decision_type,
            confidence=confidence,
            visibility=str(visibility) if visibility is not None else None,
            unit_type=str(unit_type) if unit_type is not None else None,
            source_unit=str(proposal.get("sourceUnit") or ""),
        )
        results.append(decided)
    mark_reconcile_complete(root)
    materialize = materialize_ready(root)
    if materialize.get("ready"):
        for item in materialize["ready"]:
            handoff_cmd = f"bash scripts/planning-graph.sh reconcile --apply-absorb {item.get('candidateId')}"
            handoffs.append(enqueue_handoff(root, handoff_cmd, reason="post-undo-window materialize"))
    out = {
        "verdict": "step-complete",
        "posture": posture["mode"],
        "results": results,
        "materialize": materialize,
        "handoffs": handoffs,
        "mutationBudget": check_mutation_budget(root),
    }
    budget = out["mutationBudget"]
    if budget.get("exhausted"):
        st = load_state(root)
        st["halted"] = True
        save_state(root, st)
        out["halt"] = "planning-mutation-budget"
        out["verdict"] = "halt"
    reset_dispatch_boundary(root)
    return out


def cmd_posture(root: Path, _args: argparse.Namespace) -> int:
    emit({"verdict": "ok", "posture": posture_config(root)})
    return 0


def cmd_classify(root: Path, args: argparse.Namespace) -> int:
    emit(
        {
            "verdict": "ok",
            "decisionType": args.decision_type,
            "decisionClass": classify_decision(args.decision_type),
            "evaluation": evaluate_decision(
                root,
                decision_type=args.decision_type,
                visibility=args.visibility,
                unit_type=args.unit_type,
            ),
        }
    )
    return 0


def apply_explicit_flags(root: Path, args: argparse.Namespace, decision_type: str) -> dict[str, Any] | None:
    if getattr(args, "override", False):
        log_autonomy_action(root, kind="override", why=f"override for {decision_type}")
    if getattr(args, "accept_frozen_impact", False):
        log_autonomy_action(root, kind="accept-frozen-impact", why=f"frozen impact accepted for {decision_type}")
    if getattr(args, "direct_to_trunk", False):
        log_autonomy_action(
            root,
            kind="direct-to-trunk",
            why=f"direct-to-trunk requested for {decision_type} (branch protection never bypassed)",
        )
        return {
            "verdict": "halt",
            "halt": "planning-autonomy:direct-to-trunk-logged",
            "note": "branch protection is never bypassed",
        }
    return None


def cmd_evaluate(root: Path, args: argparse.Namespace) -> int:
    flagged = apply_explicit_flags(root, args, args.decision_type)
    if flagged is not None:
        emit({"verdict": "ok", "evaluation": flagged}, exit_code=30)
    result = evaluate_decision(
        root,
        decision_type=args.decision_type,
        visibility=args.visibility,
        unit_type=args.unit_type,
    )
    exit_code = 0
    if result.get("verdict") == "refuse":
        exit_code = PRIVATE_REFUSAL_EXIT
    elif result.get("requiresConfirm"):
        exit_code = CONFIRM_EXIT
    emit({"verdict": "ok", "evaluation": result}, exit_code=exit_code)
    return 0


def cmd_auto_decide(root: Path, args: argparse.Namespace) -> int:
    emit(
        auto_decide_proposal(
            root,
            candidate_id=args.candidate_id,
            decision_type=args.decision_type,
            confidence=float(args.confidence),
            visibility=args.visibility,
            unit_type=args.unit_type,
            source_unit=args.source_unit,
        )
    )
    return 0


def cmd_enqueue(root: Path, args: argparse.Namespace) -> int:
    emit(enqueue_handoff(root, args.command, reason=args.reason or "handoff"))
    return 0


def cmd_check_dispatch(root: Path, args: argparse.Namespace) -> int:
    result = check_nested_dispatch(args.command)
    if result.get("forbidden"):
        fail("nested orchestrator dispatch forbidden", exit_code=NESTED_DISPATCH_EXIT, **result)
    emit({"verdict": "ok", **result})
    return 0


def cmd_log(root: Path, args: argparse.Namespace) -> int:
    emit(log_autonomy_action(root, kind=args.kind, why=args.why))
    return 0


def cmd_budget(root: Path, _args: argparse.Namespace) -> int:
    emit({"verdict": "ok", **check_mutation_budget(root)})
    return 0


def cmd_step(root: Path, args: argparse.Namespace) -> int:
    proposals = None
    if args.proposals_file:
        path = Path(args.proposals_file)
        data = json.loads(path.read_text(encoding="utf-8"))
        proposals = data if isinstance(data, list) else data.get("proposals")
    emit(driver_step(root, proposals=proposals))
    return 0




def cmd_undo(root: Path, args: argparse.Namespace) -> int:
    state = load_state(root)
    pending = state.get("pendingUndo") or []
    if not isinstance(pending, list):
        fail("no pending undo records")
    target = args.candidate_id
    now = datetime.now(timezone.utc)
    for item in reversed(pending):
        if str(item.get("candidateId")) != target:
            continue
        expires = parse_ts(str(item.get("undoExpiresAt", "")))
        if expires and now > expires:
            fail("undo window expired", candidateId=target)
        item["undoneAt"] = utc_now()
        item["materialized"] = False
        save_state(root, state)
        log_autonomy_action(root, kind="undo", why=f"revert auto-decide for {target}", extra={"candidateId": target})
        emit({"verdict": "ok", "action": "undo", "candidateId": target, "undoneAt": item["undoneAt"]})
    fail("candidate not found in undo window", candidateId=target)

def cmd_materialize(root: Path, _args: argparse.Namespace) -> int:
    emit(materialize_ready(root))
    return 0


def cmd_reconcile_complete(root: Path, _args: argparse.Namespace) -> int:
    emit(mark_reconcile_complete(root))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="PRD 035 planning autonomy posture driver")
    parser.add_argument("root", nargs="?", default=".")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("posture").set_defaults(func=cmd_posture)

    p_classify = sub.add_parser("classify")
    p_classify.add_argument("--decision-type", required=True)
    p_classify.add_argument("--visibility")
    p_classify.add_argument("--unit-type")
    p_classify.set_defaults(func=cmd_classify)

    p_eval = sub.add_parser("evaluate")
    p_eval.add_argument("--decision-type", required=True)
    p_eval.add_argument("--visibility")
    p_eval.add_argument("--unit-type")
    p_eval.add_argument("--override", action="store_true")
    p_eval.add_argument("--accept-frozen-impact", action="store_true")
    p_eval.add_argument("--direct-to-trunk", action="store_true")
    p_eval.set_defaults(func=cmd_evaluate)

    p_auto = sub.add_parser("auto-decide")
    p_auto.add_argument("--candidate-id", required=True)
    p_auto.add_argument("--decision-type", default="gap-absorb")
    p_auto.add_argument("--confidence", type=float, default=0.9)
    p_auto.add_argument("--visibility")
    p_auto.add_argument("--unit-type")
    p_auto.add_argument("--source-unit")
    p_auto.set_defaults(func=cmd_auto_decide)

    p_enqueue = sub.add_parser("enqueue-handoff")
    p_enqueue.add_argument("--command", required=True)
    p_enqueue.add_argument("--reason", default="")
    p_enqueue.set_defaults(func=cmd_enqueue)

    p_check = sub.add_parser("check-dispatch")
    p_check.add_argument("--command", required=True)
    p_check.set_defaults(func=cmd_check_dispatch)

    p_log = sub.add_parser("log-action")
    p_log.add_argument("--kind", required=True)
    p_log.add_argument("--why", required=True)
    p_log.set_defaults(func=cmd_log)

    sub.add_parser("budget").set_defaults(func=cmd_budget)
    p_undo = sub.add_parser("undo")
    p_undo.add_argument("--candidate-id", required=True)
    p_undo.set_defaults(func=cmd_undo)

    sub.add_parser("materialize").set_defaults(func=cmd_materialize)
    sub.add_parser("reconcile-complete").set_defaults(func=cmd_reconcile_complete)

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
