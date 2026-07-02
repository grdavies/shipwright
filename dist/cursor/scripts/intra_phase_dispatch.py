#!/usr/bin/env python3
"""Intra-phase fan-out, no-nesting guard, and dispatch decision logging (PRD 023 R15–R17)."""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from capability_select import normalize_signal_context
from wave_json_io import read_json, write_json

DECISIONS_FILENAME = "dispatch-decisions.json"
PHASE_CONTEXT_FILENAME = "phase-context.json"
DURABLE_PHASE_FILES = frozenset({"ship-steps.json", "status.json"})
DEFAULT_PARALLEL_BUDGET = 2
DEFAULT_HARNESS_LIMIT = 8
DECISION_VERSION = 1
EXECUTE_PLAN_FILENAME = "execute-step-plan.json"


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                return read_json(path)
            except (json.JSONDecodeError, OSError):
                continue
    return {}


def intra_phase_settings(config: dict[str, Any]) -> dict[str, int]:
    worktree = config.get("worktree") or {}
    intra = config.get("intraPhase") or {}
    ceiling = int(worktree.get("parallelCeiling") or 4)
    budget = int(intra.get("parallelBudget") or DEFAULT_PARALLEL_BUDGET)
    harness = int(intra.get("harnessLimit") or DEFAULT_HARNESS_LIMIT)
    return {
        "parallelCeiling": max(1, ceiling),
        "parallelBudget": max(1, budget),
        "harnessLimit": max(1, harness),
        "globalCap": max(1, min(ceiling, harness)),
    }


def normalize_files(files: list[Any] | None) -> list[str]:
    if not isinstance(files, list):
        return []
    return sorted({str(f).replace("\\", "/") for f in files if f})


def paths_overlap(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return False
    for a in left:
        for b in right:
            if a == b:
                return True
            if fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
                return True
    return False


def partition_overlap(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_tasks = normalize_files(left.get("tasks"))
    right_tasks = normalize_files(right.get("tasks"))
    if left_tasks and right_tasks and set(left_tasks) & set(right_tasks):
        return True
    left_files = normalize_files(left.get("files"))
    right_files = normalize_files(right.get("files"))
    if paths_overlap(left_files, right_files):
        left_key = str(left.get("partitionKey") or left.get("workerId") or "")
        right_key = str(right.get("partitionKey") or right.get("workerId") or "")
        left_ro = bool(left.get("readOnly")) or not left_files
        right_ro = bool(right.get("readOnly")) or not right_files
        if left_ro and right_ro and left_key and right_key and left_key != right_key:
            return False
        return True
    return False


def validate_disjoint_partition(partitions: list[dict[str, Any]]) -> dict[str, Any]:
    if not partitions:
        return {
            "verdict": "reject",
            "cause": "partition:missing",
            "reason": "fan-out requires a declared disjoint file/task partition",
        }
    for idx, part in enumerate(partitions):
        if not isinstance(part, dict):
            return {
                "verdict": "reject",
                "cause": "partition:invalid",
                "reason": f"partition[{idx}] must be an object",
            }
        worker = part.get("workerId") or part.get("agent")
        if not worker:
            return {
                "verdict": "reject",
                "cause": "partition:invalid",
                "reason": f"partition[{idx}] missing workerId/agent",
            }
    overlaps: list[dict[str, str]] = []
    for i in range(len(partitions)):
        for j in range(i + 1, len(partitions)):
            if partition_overlap(partitions[i], partitions[j]):
                overlaps.append(
                    {
                        "left": str(partitions[i].get("workerId") or partitions[i].get("agent")),
                        "right": str(partitions[j].get("workerId") or partitions[j].get("agent")),
                    }
                )
    if overlaps:
        return {
            "verdict": "serialize",
            "cause": "partition:overlap",
            "overlaps": overlaps,
            "reason": "overlapping partitions must be serialized or rejected",
        }
    return {"verdict": "pass", "partitions": partitions}


def check_global_cap(
    wave_slots: int,
    active_intra_phase: int,
    proposed_workers: int,
    settings: dict[str, int],
) -> dict[str, Any]:
    wave_slots = max(0, int(wave_slots))
    active_intra_phase = max(0, int(active_intra_phase))
    proposed_workers = max(0, int(proposed_workers))
    global_cap = settings["globalCap"]
    combined = wave_slots + active_intra_phase + proposed_workers
    remaining = global_cap - (wave_slots + active_intra_phase)
    if combined > global_cap:
        return {
            "verdict": "reject",
            "cause": "cap:global",
            "waveSlots": wave_slots,
            "activeIntraPhase": active_intra_phase,
            "proposedWorkers": proposed_workers,
            "globalCap": global_cap,
            "reason": (
                f"waveSlots({wave_slots}) + activeIntraPhase({active_intra_phase}) + "
                f"proposed({proposed_workers}) exceeds global cap {global_cap}"
            ),
        }
    budget = settings["parallelBudget"]
    if proposed_workers > budget:
        return {
            "verdict": "reject",
            "cause": "cap:intra-phase-budget",
            "parallelBudget": budget,
            "proposedWorkers": proposed_workers,
            "reason": f"proposed workers {proposed_workers} exceed intraPhase.parallelBudget {budget}",
        }
    return {
        "verdict": "pass",
        "waveSlots": wave_slots,
        "activeIntraPhase": active_intra_phase,
        "proposedWorkers": proposed_workers,
        "globalCap": global_cap,
        "parallelBudget": budget,
        "remainingIntraPhaseSlots": max(0, remaining),
    }


def load_phase_context(run_dir: Path) -> dict[str, Any]:
    path = run_dir / PHASE_CONTEXT_FILENAME
    if not path.is_file():
        return {}
    data = read_json(path)
    return data if isinstance(data, dict) else {}


def resolve_conductor_mode(signal_context: dict[str, Any], run_dir: Path | None) -> str | None:
    ctx_mode = signal_context.get("conductor_mode")
    if ctx_mode:
        return str(ctx_mode).strip().lower()
    if run_dir is not None:
        stamped = load_phase_context(run_dir).get("conductor_mode")
        if stamped:
            return str(stamped).strip().lower()
    return None


def propose_fan_out(
    signal_context: dict[str, Any],
    workers: list[dict[str, Any]] | None,
    settings: dict[str, int],
) -> dict[str, Any]:
    normalized = normalize_signal_context(signal_context)
    file_paths = normalize_files(normalized.get("file_paths"))
    candidates = workers or []
    if not candidates:
        tags = list(normalized.get("derived_tags") or [])
        if "review-panel" in tags or normalized.get("phase_type") == "ship":
            candidates = [
                {"workerId": "correctness", "readOnly": True},
                {"workerId": "security", "readOnly": True},
                {"workerId": "maintainability", "readOnly": True},
            ]
    partitions: list[dict[str, Any]] = []
    for worker in candidates:
        worker_id = str(worker.get("workerId") or worker.get("agent") or "")
        if not worker_id:
            continue
        declared_files = normalize_files(worker.get("files"))
        if not declared_files and file_paths and not worker.get("readOnly"):
            chunk_size = max(1, (len(file_paths) + len(candidates) - 1) // len(candidates))
            idx = len(partitions)
            declared_files = file_paths[idx * chunk_size : (idx + 1) * chunk_size]
        entry: dict[str, Any] = {
            "workerId": worker_id,
            "files": declared_files,
            "tasks": normalize_files(worker.get("tasks")),
            "readOnly": bool(worker.get("readOnly")),
        }
        if worker.get("readOnly") or not declared_files:
            entry["partitionKey"] = f"reviewer:{worker_id}"
        partitions.append(entry)
    max_workers = min(len(partitions), settings["parallelBudget"])
    return {
        "partitions": partitions,
        "proposedWorkers": max_workers,
        "signals": {
            "fileCount": len(file_paths),
            "derivedTags": list(normalized.get("derived_tags") or []),
            "phaseType": normalized.get("phase_type"),
        },
    }



def execute_plan_parallel_batches(run_dir: Path | None) -> bool:
    if run_dir is None:
        return False
    path = run_dir / EXECUTE_PLAN_FILENAME
    if not path.is_file():
        return False
    try:
        plan = read_json(path)
    except (json.JSONDecodeError, OSError):
        return False
    for batch in plan.get("batches") or []:
        if isinstance(batch, list) and len(batch) > 1:
            return True
    refs = plan.get("refs") or []
    return isinstance(refs, list) and len(refs) > 1


def execute_tier_carve_out(signal_context: dict[str, Any], run_dir: Path | None) -> bool:
    normalized = normalize_signal_context(signal_context)
    tier = str(normalized.get("tier") or normalized.get("dispatch_tier") or "").lower()
    partition = str(normalized.get("partition") or normalized.get("partitionKey") or "").lower()
    if tier == "execute" or partition == "execute" or normalized.get("phase_type") == "execute":
        return execute_plan_parallel_batches(run_dir)
    return False

def evaluate_dispatch(
    *,
    root: Path,
    signal_context: dict[str, Any],
    proposal: dict[str, Any] | None,
    wave_slots: int,
    active_intra_phase: int,
    run_dir: Path | None,
    record: bool,
) -> dict[str, Any]:
    config = load_workflow_config(root)
    settings = intra_phase_settings(config)
    normalized = normalize_signal_context(signal_context)
    mode = resolve_conductor_mode(normalized, run_dir)

    if mode == "background_phase":
        carve_out = execute_tier_carve_out(normalized, run_dir)
        if carve_out:
            decision = {
                "timestamp": utc_now(),
                "signals": {
                    "conductorMode": mode,
                    "fileCount": len(normalize_files(normalized.get("file_paths"))),
                    "executeCarveOut": True,
                },
                "declaredPartition": [],
                "chosenParallelism": {
                    "mode": "parallel",
                    "workers": 1,
                    "taskSpawnAllowed": True,
                    "partition": "execute",
                },
                "degradeReason": None,
                "readOnlyDurableFiles": sorted(DURABLE_PHASE_FILES),
            }
            result = {
                "verdict": "parallel",
                "cause": "execute-carve-out",
                "taskSpawnAllowed": True,
                "workers": 1,
                "partition": "execute",
                "decision": decision,
                "reason": "background_phase execute-tier carve-out when execute plan has parallel batches (R14/R45)",
            }
            if record and run_dir is not None:
                append_decision(run_dir, decision)
            return result
        decision = {
            "timestamp": utc_now(),
            "signals": {
                "conductorMode": mode,
                "fileCount": len(normalize_files(normalized.get("file_paths"))),
            },
            "declaredPartition": [],
            "chosenParallelism": {
                "mode": "inline",
                "workers": 0,
                "taskSpawnAllowed": False,
            },
            "degradeReason": "background_phase",
            "readOnlyDurableFiles": sorted(DURABLE_PHASE_FILES),
        }
        result = {
            "verdict": "inline",
            "cause": "nesting:background-phase",
            "taskSpawnAllowed": False,
            "decision": decision,
            "reason": "background_phase refuses intra-phase Task dispatch before spawn (R16)",
        }
        if record and run_dir is not None:
            append_decision(run_dir, decision)
        return result

    if mode == "execute_fan_out":
        partitions = list((proposal or {}).get("partitions") or [])
        if not partitions and normalized.get("task_ref"):
            partitions = [
                {
                    "workerId": str(normalized.get("task_ref")),
                    "files": normalize_files(normalized.get("file_paths")),
                    "tasks": [str(normalized.get("task_ref"))],
                    "partitionKey": "execute",
                }
            ]
        proposed_workers = max(1, int((proposal or {}).get("proposedWorkers") or len(partitions) or 1))
        cap_check = check_global_cap(wave_slots, active_intra_phase, proposed_workers, settings)
        if cap_check["verdict"] == "reject":
            decision = _decision_record(
                normalized,
                partitions,
                {"mode": "inline", "workers": 0, "taskSpawnAllowed": False},
                cap_check.get("cause"),
            )
            result = {
                "verdict": "reject",
                "cause": cap_check["cause"],
                "taskSpawnAllowed": False,
                "cap": cap_check,
                "decision": decision,
            }
            if record and run_dir is not None:
                append_decision(run_dir, decision)
            return result
        chosen = {
            "mode": "parallel",
            "workers": proposed_workers,
            "taskSpawnAllowed": True,
            "partition": "execute",
        }
        decision = _decision_record(normalized, partitions, chosen, None)
        decision["readOnlyDurableFiles"] = sorted(DURABLE_PHASE_FILES)
        result = {
            "verdict": "parallel",
            "taskSpawnAllowed": True,
            "workers": proposed_workers,
            "partition": "execute",
            "cap": cap_check,
            "decision": decision,
            "reason": "execute_fan_out permits nested execute Tasks (R14)",
        }
        if record and run_dir is not None:
            append_decision(run_dir, decision)
        return result

    fan_out = proposal or propose_fan_out(normalized, None, settings)
    partitions = list(fan_out.get("partitions") or [])
    proposed_workers = int(fan_out.get("proposedWorkers") or len(partitions))

    partition_check = validate_disjoint_partition(partitions)
    if partition_check["verdict"] == "reject":
        decision = _decision_record(
            normalized,
            partitions,
            {"mode": "inline", "workers": 0, "taskSpawnAllowed": False},
            partition_check.get("cause"),
        )
        result = {
            "verdict": "reject",
            "cause": partition_check["cause"],
            "taskSpawnAllowed": False,
            "partition": partition_check,
            "decision": decision,
        }
        if record and run_dir is not None:
            append_decision(run_dir, decision)
        return result

    cap_check = check_global_cap(wave_slots, active_intra_phase, proposed_workers, settings)
    if cap_check["verdict"] == "reject":
        decision = _decision_record(
            normalized,
            partitions,
            {"mode": "inline", "workers": 0, "taskSpawnAllowed": False},
            cap_check.get("cause"),
        )
        result = {
            "verdict": "reject",
            "cause": cap_check["cause"],
            "taskSpawnAllowed": False,
            "cap": cap_check,
            "decision": decision,
        }
        if record and run_dir is not None:
            append_decision(run_dir, decision)
        return result

    if partition_check["verdict"] == "serialize":
        chosen = {"mode": "serialize", "workers": 1, "taskSpawnAllowed": True}
        degrade = "partition:overlap"
    elif proposed_workers <= 1:
        chosen = {"mode": "inline", "workers": 1, "taskSpawnAllowed": False}
        degrade = None
    else:
        chosen = {
            "mode": "parallel",
            "workers": proposed_workers,
            "taskSpawnAllowed": True,
        }
        degrade = None

    decision = _decision_record(normalized, partitions, chosen, degrade)
    decision["readOnlyDurableFiles"] = sorted(DURABLE_PHASE_FILES)
    result = {
        "verdict": chosen["mode"],
        "taskSpawnAllowed": chosen["taskSpawnAllowed"],
        "workers": chosen["workers"],
        "partition": partition_check,
        "cap": cap_check,
        "decision": decision,
    }
    if record and run_dir is not None:
        append_decision(run_dir, decision)
    return result


def _decision_record(
    signal_context: dict[str, Any],
    partitions: list[dict[str, Any]],
    chosen: dict[str, Any],
    degrade_reason: str | None,
) -> dict[str, Any]:
    normalized = normalize_signal_context(signal_context)
    return {
        "timestamp": utc_now(),
        "signals": {
            "fileCount": len(normalize_files(normalized.get("file_paths"))),
            "derivedTags": list(normalized.get("derived_tags") or []),
            "conductorMode": normalized.get("conductor_mode"),
            "phaseType": normalized.get("phase_type"),
        },
        "declaredPartition": partitions,
        "chosenParallelism": chosen,
        "degradeReason": degrade_reason,
    }


def decisions_path(run_dir: Path) -> Path:
    return run_dir / DECISIONS_FILENAME


def append_decision(run_dir: Path, decision: dict[str, Any]) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = decisions_path(run_dir)
    if path.is_file():
        doc = read_json(path)
    else:
        doc = {"version": DECISION_VERSION, "decisions": []}
    if not isinstance(doc.get("decisions"), list):
        doc["decisions"] = []
    doc["decisions"].append(decision)
    write_json(path, doc)
    return path


def stamp_phase_context(run_dir: Path, conductor_mode: str) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / PHASE_CONTEXT_FILENAME
    write_json(
        path,
        {
            "version": 1,
            "conductor_mode": conductor_mode,
            "stampedAt": utc_now(),
        },
    )
    return path


def parse_json_arg(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def cmd_stamp_context(args: argparse.Namespace) -> None:
    if not args.run_dir:
        fail("--run-dir required")
    mode = str(args.conductor_mode or "inline").strip().lower()
    if mode not in {"inline", "background_phase", "execute_fan_out"}:
        fail("--conductor-mode must be inline, background_phase, or execute_fan_out")
    path = stamp_phase_context(Path(args.run_dir), mode)
    emit({"verdict": "pass", "action": "stamp-context", "path": str(path), "conductorMode": mode})


def cmd_evaluate(root: Path, args: argparse.Namespace) -> None:
    signal_context = parse_json_arg(args.context_json, {})
    proposal = parse_json_arg(args.proposal_json, None)
    run_dir = Path(args.run_dir) if args.run_dir else None
    result = evaluate_dispatch(
        root=root,
        signal_context=signal_context,
        proposal=proposal,
        wave_slots=int(args.wave_slots or 0),
        active_intra_phase=int(args.active_intra_phase or 0),
        run_dir=run_dir,
        record=bool(args.record),
    )
    exit_code = 0 if result.get("verdict") in {"parallel", "inline", "serialize"} else 20
    if result.get("verdict") == "reject":
        exit_code = 20
    emit(result, exit_code)


def cmd_check_nesting(root: Path, args: argparse.Namespace) -> None:
    signal_context = parse_json_arg(args.context_json, {})
    run_dir = Path(args.run_dir) if args.run_dir else None
    result = evaluate_dispatch(
        root=root,
        signal_context=signal_context,
        proposal=None,
        wave_slots=0,
        active_intra_phase=0,
        run_dir=run_dir,
        record=False,
    )
    allowed = bool(result.get("taskSpawnAllowed"))
    emit(
        {
            "verdict": "pass" if not allowed and result.get("cause") == "nesting:background-phase" else (
                "pass" if allowed else "fail"
            ),
            "taskSpawnAllowed": allowed,
            "nestedTaskSpawns": 0 if not allowed else None,
            "evaluation": result,
        },
        0 if not allowed or allowed else 20,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Intra-phase dispatch policy (PRD 023 R15–R17)")
    sub = parser.add_subparsers(dest="command", required=True)

    stamp = sub.add_parser("stamp-context", help="Stamp conductor_mode to per-phase run dir")
    stamp.add_argument("--run-dir", required=True)
    stamp.add_argument("--conductor-mode", default="inline")

    evaluate = sub.add_parser("evaluate", help="Validate fan-out proposal and optionally record decision")
    evaluate.add_argument("--context-json", default="{}")
    evaluate.add_argument("--proposal-json", default="")
    evaluate.add_argument("--wave-slots", default="0")
    evaluate.add_argument("--active-intra-phase", default="0")
    evaluate.add_argument("--run-dir", default="")
    evaluate.add_argument("--record", action="store_true")

    nesting = sub.add_parser("check-nesting", help="Pre-dispatch no-nesting guard")
    nesting.add_argument("--run-dir", default="")
    nesting.add_argument("--context-json", default="{}")

    return parser


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: intra_phase_dispatch.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    command = sys.argv[2]
    parser = build_parser()
    args = parser.parse_args([command, *sys.argv[3:]])
    if args.command == "stamp-context":
        cmd_stamp_context(args)
    elif args.command == "evaluate":
        cmd_evaluate(root, args)
    elif args.command == "check-nesting":
        cmd_check_nesting(root, args)
    else:
        fail(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
