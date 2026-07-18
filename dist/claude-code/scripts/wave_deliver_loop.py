#!/usr/bin/env python3
"""Durable deliver-loop driver for phase-mode /sw-deliver (PRD 007 R1–R12, R46)."""
from __future__ import annotations

import json
import os
import subprocess
import time

from _sw import interpreter
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sw_scripts_resolve import resolve_script

from wave_json_io import StateCorruptError, read_json, write_json

from plan_persist import (
    LIFECYCLE_PHASE_PLAN_PENDING,
    LIFECYCLE_PHASE_PLAN_VALIDATED,
    LIFECYCLE_WAVE_VALIDATED,
    get_lifecycle,
    needs_phase_plan_proposal,
    persist_wave_batching_plan,
    set_phase_lifecycle,
    set_wave_lifecycle,
    wave_lifecycle,
    wave_plan_ready,
)
from deliver_plan_surfacing import (
    surface_phase_plan_chosen,
    surface_wave_plan_chosen,
)
from wave_plan_validate import (
    phase_fallback_canonical_chain,
    read_config_plan_policy,
    validate_wave_plan,
    wave_fallback_canonical_waves,
)


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from wave_merge import (
    VALID_STATUS_VERDICTS,
    check_status_sha,
    phase_branch_head_optional,
    read_phase_status_optional,
    status_file_for,
)
from status_integrity import (
    classify_deliver_stall_cause,
    DEFAULT_REEMIT_MAX,
    is_differentiated_stall,
    stall_progress_key,
    DEFAULT_TIP_QUIESCENCE_SECONDS,
    build_status_document,
    classify_stuck_stale,
    derive_terminal_verdict_from_live_evidence,
    live_host_evidence_ok,
    resolve_pr_number,
    status_is_consumable_terminal,
    validate_terminal_status_shape,
    write_status_atomic,
)
from wave_state import (
    TERMINAL_PHASE_STATUSES,
    append_log as state_append_log,
    load_deliver_state,
    resolve_state_path,
    save_deliver_state,
    scoped_paths,
    target_branch_from_state,
    ensure_canonical_state_synced,
    sync_canonical_state_read,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PLAN_PATH = Path(".cursor/sw-deliver-plan.json")
BLOCKER_PATH = Path(".cursor/sw-deliver-runs/blockers.json")

MECHANICAL_ACTIONS = frozenset(
    {
        "plan",
        "base-capture",
        "spec-seed",
        "state-init",
        "lock-acquire",
        "inflight-signal-write",
        "inflight-signal-clear",
        "orchestrator-provision",
        "provision-phase",
        "dispatch-ship",
        "dispatch-batch",
        "collect-all-ready",
        "collect-status",
        "canonical-reemit",
        "merge-enqueue",
        "merge-run-next",
        "post-merge-verify-remediate",
        "phase-teardown-run",
        "advance-wave",
        "wave-plan-persist",
        "phase-plan-entry",
        "write-blocker-report",
        "all-phases-complete",
        "finalize-completion",
        "suggest-cleanup",
    }
)
AGENT_ACTIONS = frozenset(
    {
        "remediate",
        "terminal-ship",
        "terminal-checkpoint",
        "retrospective",
        "compound-ship",
    }
)
AWAIT_ACTIONS = frozenset({"await-in-flight"})
TERMINAL_ACTIONS = frozenset({"halt-blocked", "complete", "terminal"})

DRIVER_STALE_SECONDS = int(os.environ.get("SW_DRIVER_STALE_SECONDS", "7200"))
DEFAULT_REMEDIATION_MAX = 2
DEFAULT_PHASE_TIMEOUT_MIN = int(os.environ.get("SW_PHASE_TIMEOUT_MINUTES", "240"))
DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN = int(
    os.environ.get("SW_BACKGROUND_TASK_TIMEOUT_MINUTES", "120")
)
MERGED_PHASE_STATUSES = TERMINAL_PHASE_STATUSES  # re-export (R1); do not redefine locally
DEFAULT_MAX_ITERATIONS = 500
DEFAULT_NO_PROGRESS_THRESHOLD = 3
DRAIN_STEP_BUDGET_HALT = "conductor:drain-step-budget-exceeded"
_MECH_TIMER_START: float | None = None
PROPOSAL_OVERHEAD_ACTIONS = frozenset({"wave-plan-persist", "phase-plan-entry"})
BUDGET_HALT_CAUSES = frozenset(
    {
        "conductor:max-iterations-exceeded",
        "conductor:max-run-minutes-exceeded",
        "conductor:no-progress",
        "conductor:plan-rejection-breaker",
        "plan-rejection-breaker",
        DRAIN_STEP_BUDGET_HALT,
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_remediation_cause(meta: dict[str, Any], cause: str) -> None:
    history = meta.setdefault("remediationCauseHistory", [])
    if not isinstance(history, list):
        history = []
        meta["remediationCauseHistory"] = history
    if history and history[-1] == cause:
        meta["lastRemediationCause"] = cause
        return
    history.append(cause)
    meta["lastRemediationCause"] = cause


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


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def remediation_max(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    remediation = deliver.get("remediation") or {}
    raw = remediation.get("maxAttempts", DEFAULT_REMEDIATION_MAX)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_REMEDIATION_MAX


def phase_timeout_minutes(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    watchdog = deliver.get("watchdog") or {}
    raw = watchdog.get("phaseTimeoutMinutes", DEFAULT_PHASE_TIMEOUT_MIN)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_PHASE_TIMEOUT_MIN


def background_task_timeout_minutes(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    watchdog = deliver.get("watchdog") or {}
    raw = watchdog.get("backgroundTaskTimeoutMinutes", DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN


def parallel_ceiling(root: Path) -> int:
    worktree = load_workflow_config(root).get("worktree") or {}
    raw = worktree.get("parallelCeiling", 4)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 4


def autonomy_config(root: Path) -> dict[str, Any]:
    deliver = load_workflow_config(root).get("deliver") or {}
    autonomy = deliver.get("autonomy") or {}
    return autonomy if isinstance(autonomy, dict) else {}


def max_iterations(root: Path) -> int:
    raw = autonomy_config(root).get("maxIterations", DEFAULT_MAX_ITERATIONS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ITERATIONS


def max_run_minutes(root: Path) -> int | None:
    raw = autonomy_config(root).get("maxRunMinutes")
    if raw is None:
        return None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return None


def no_progress_threshold(_root: Path) -> int:
    return DEFAULT_NO_PROGRESS_THRESHOLD


def drain_mechanical_enabled(root: Path) -> bool:
    deliver = load_workflow_config(root).get("deliver") or {}
    loop = deliver.get("loop") or {}
    raw = loop.get("drainMechanical", True)
    return raw if isinstance(raw, bool) else True


def status_reemit_max(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    status_reemit = deliver.get("statusReemit") or {}
    raw = status_reemit.get("maxAttempts", DEFAULT_REEMIT_MAX)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_REEMIT_MAX


def tip_quiescence_seconds(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    status_reemit = deliver.get("statusReemit") or {}
    raw = status_reemit.get("tipQuiescenceSeconds", DEFAULT_TIP_QUIESCENCE_SECONDS)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_TIP_QUIESCENCE_SECONDS


def detect_stuck_stale_phase(
    root: Path,
    state: dict[str, Any],
    pid: str,
    meta: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    slug = str(meta.get("slug") or pid)
    phase_branch = meta.get("branch")
    if not phase_branch:
        return False, {"reason": "missing-branch"}
    branch_head = phase_branch_head_optional(root, state, slug, str(phase_branch))
    if not branch_head:
        return False, {"reason": "missing-branch-head"}
    _, status = read_phase_status_optional(root, slug, state)
    pr_number = resolve_pr_number(root, state, slug, status, str(phase_branch))
    return classify_stuck_stale(
        root,
        phase_slug=slug,
        phase_branch=str(phase_branch),
        branch_head=branch_head,
        status=status,
        pr_number=pr_number,
        quiescence_seconds=tip_quiescence_seconds(root),
    )


def terminal_autonomy_mode(root: Path) -> str:
    deliver = load_workflow_config(root).get("deliver") or {}
    terminal = deliver.get("terminal") or {}
    mode = terminal.get("autonomy", "supervised")
    return mode if mode in ("supervised", "auto") else "supervised"


def orchestrator_worktree_path(root: Path, state: dict[str, Any]) -> Path | None:
    orch = state.get("orchestratorWorktree") or {}
    raw = orch.get("path")
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = (root / path).resolve()
    return path if path.is_dir() else None

def _is_basename_only_path(raw: str) -> bool:
    cleaned = raw.strip()
    return bool(cleaned) and '/' not in cleaned and chr(92) not in cleaned and not cleaned.startswith('.')


def _path_under_managed_roots(path: Path, repo_root: Path) -> bool:
    from worktree_lib import list_all_worktree_roots

    resolved = path.resolve()
    for root in list_all_worktree_roots(repo_root):
        root_resolved = root.resolve()
        if resolved == root_resolved:
            return True
        try:
            resolved.relative_to(root_resolved)
            return True
        except ValueError:
            continue
    return False


def _orchestrator_lock_reclaimable(root: Path, target: str) -> bool:
    from wave_state import lock_owner_live, read_lock_meta, scoped_paths

    lock_path = scoped_paths(root, target)["lock"]
    if not lock_path.is_file():
        return True
    meta = read_lock_meta(lock_path)
    return not lock_owner_live(meta)


def try_adopt_recorded_orchestrator_worktree(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    """Auto-adopt durable orchestratorWorktree on resume (PRD 068 R2)."""
    orch = state.get("orchestratorWorktree") or {}
    raw_path = orch.get("path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return {"adopted": False, "reason": "no-recorded-path"}
    if _is_basename_only_path(raw_path):
        fail(
            "orchestrator worktree path is basename-only; refusing invent",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-basename-only",
            path=raw_path,
        )
    from wave_state import canonical_repo_root, slug_from_target, target_branch_from_state

    repo_root = canonical_repo_root(root)
    path = Path(raw_path)
    if not path.is_absolute():
        path = (repo_root / path).resolve()
    else:
        path = path.resolve()
    if not _path_under_managed_roots(path, repo_root):
        fail(
            "orchestrator worktree path is outside managed roots",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-unmanaged-path",
            path=str(path),
        )
    if not path.is_dir():
        fail(
            "recorded orchestrator worktree path is missing",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-path-missing",
            path=str(path),
        )
    target = target_branch_from_state(state) or (plan.get("target") or {}).get("branch")
    if not isinstance(target, str) or not target:
        fail(
            "cannot resolve target branch for orchestrator adopt",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-missing-target",
        )
    recorded_branch = orch.get("branch")
    if isinstance(recorded_branch, str) and recorded_branch and recorded_branch != target:
        fail(
            f"orchestrator worktree branch mismatch: {recorded_branch!r} vs {target!r}",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-branch-mismatch",
            recorded=recorded_branch,
            expected=target,
        )
    expected_name = f"{slug_from_target(target)}-orchestrator"
    recorded_name = str(orch.get("name") or "")
    if recorded_name and recorded_name != expected_name and path.name != expected_name:
        fail(
            "orchestrator worktree slug/name mismatch",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-slug-mismatch",
            expectedName=expected_name,
            recordedName=recorded_name,
            pathName=path.name,
        )
    from wave_lifecycle import (
        adopt_orchestrator_worktree,
        git_toplevel,
        orchestrator_worktree_branch,
        orchestrator_worktree_dirty,
    )

    current = orchestrator_worktree_branch(path)
    if current != target:
        fail(
            f"orchestrator worktree on {current!r}, expected {target!r}",
            exit_code=20,
            halt="orchestrator-adopt",
            cause="resume:orchestrator-branch-mismatch",
            actual=current,
            expected=target,
        )
    if orchestrator_worktree_dirty(path):
        fail(
            f"orchestrator worktree is dirty: {path}",
            exit_code=20,
            halt="dirty-orchestrator",
            cause="resume:orchestrator-dirty",
            path=str(path),
        )
    if not _orchestrator_lock_reclaimable(repo_root, target):
        fail(
            "orchestrator lock held and not reclaimable",
            exit_code=20,
            halt="orchestrator-lock-held",
            cause="resume:orchestrator-lock-held",
            target=target,
        )
    if root.resolve() == path.resolve():
        return {"adopted": False, "reason": "already-in-orchestrator-cwd", "path": str(path)}
    proc = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    tip = proc.stdout.strip() if proc.returncode == 0 else ""
    adopt_orchestrator_worktree(
        root,
        top=git_toplevel(repo_root),
        path=path,
        name=path.name,
        target=target,
        tip=tip,
    )
    return {"adopted": True, "path": str(path), "branch": target, "name": path.name}


def apply_resume_entry(root: Path, state: dict[str, Any], plan: dict[str, Any], args: list[str]) -> dict[str, Any]:
    """Resume short-circuit + orchestrator adopt on deliver-loop entry (PRD 068 R1/R2)."""
    from wave_deliver import evaluate_resume_short_circuit

    resume = evaluate_resume_short_circuit(root, args)
    if resume.get("halt"):
        fail(
            f"resume blocked: {resume.get('cause')}",
            exit_code=20,
            halt=resume.get("cause", "resume-blocked"),
            cause=resume.get("cause"),
            **{k: v for k, v in resume.items() if k not in ("halt", "consumable", "state")},
        )
    adopt: dict[str, Any] = {"adopted": False}
    if resume.get("consumable") and state.get("orchestratorWorktree"):
        adopt = try_adopt_recorded_orchestrator_worktree(root, state, plan)
    return {"resume": resume, "orchestratorAdopt": adopt}

def fixture_tree_clean_or_halt(root: Path, state: dict[str, Any]) -> None:
    """PRD 050 R52 — fail closed when orchestrator fixture tree is dirty before merge-run-next."""
    orch = orchestrator_worktree_path(root, state)
    if orch is None:
        fail(
            "cannot resolve orchestrator worktree for fixture-tree doctor",
            exit_code=20,
            halt="fixture-tree-doctor",
            remediation="provision orchestrator worktree before merge-run-next",
        )
    proc = subprocess.run(
        ["git", "-C", str(orch), "status", "--porcelain", "scripts/test/fixtures/"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    if dirty:
        fail(
            "tracked scripts/test/fixtures dirty in orchestrator worktree",
            exit_code=20,
            halt="fixture-tree-drift",
            paths=dirty,
            remediation="git checkout -- scripts/test/fixtures/",
            orchestratorWorktree=str(orch),
        )



def resolve_currency_check(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> tuple[Path, str] | tuple[None, None]:
    """Resolve ledger check root + tasks path (R7 — integration worktree when list lives there).

    R2: under issue-store prefer the materialized path when the logical docs/ path is absent.
    """
    raw = task_list_from(state, plan)
    if not raw:
        return None, None
    rel = str(raw)
    try:
        import planning_materialize as pm
        import planning_path_redirect

        pm.ensure_run_entry_materialized(root, rel)
        _resolved, readable = planning_path_redirect.resolve_readable_path(root, rel)
        if readable is not None and readable.is_file():
            try:
                rel_for_check = str(readable.relative_to(root.resolve()))
            except ValueError:
                rel_for_check = str(readable)
            return root, rel_for_check
    except Exception:
        pass
    candidates: list[Path] = [root]
    orch = orchestrator_worktree_path(root, state)
    if orch is not None:
        candidates.append(orch)
    for check_root in candidates:
        task_path = Path(rel)
        if not task_path.is_absolute():
            task_path = (check_root / rel).resolve()
        if task_path.is_file():
            try:
                rel_for_check = str(task_path.relative_to(check_root.resolve()))
            except ValueError:
                rel_for_check = str(task_path)
            return check_root, rel_for_check
    return root, rel


def blocker_cause_class(cause: str) -> str:
    if cause in BUDGET_HALT_CAUSES or cause.startswith("conductor:"):
        return "budget"
    if cause.startswith("verify:environmental"):
        return "environmental"
    if cause.startswith("verify:"):
        return "regression"
    return "operational"


def supersede_stale_blockers(root: Path) -> bool:
    """Supersede stale blockers.json when the driver makes progress (R11)."""
    path = root / BLOCKER_PATH
    if not path.is_file():
        return False
    try:
        prior = read_json(path)
    except (StateCorruptError, json.JSONDecodeError, OSError):
        prior = {}
    if prior.get("verdict") == "superseded":
        return False
    write_json(
        path,
        {
            "verdict": "superseded",
            "supersededAt": utc_now(),
            "priorCause": prior.get("cause"),
            "note": "Stale blockers superseded on driver progress (R11)",
        },
    )
    return True


def init_budget_counters(state: dict[str, Any]) -> None:
    state.setdefault("runStartedAt", utc_now())
    state.setdefault("driverIterationCount", 0)
    state.setdefault("noProgressStreak", 0)
    state.setdefault(
        "budgetCounters",
        {"proposalOverheadCount": 0, "executionIterationCount": 0},
    )
    state.setdefault("lastProgressKey", None)


def build_state_signature(state: dict[str, Any]) -> str:
    phases = state.get("phases") or {}
    status_map: dict[str, str] = {}
    cause_map: dict[str, str | None] = {}
    last_remediation: dict[str, str | None] = {}
    stabilize_pass: dict[str, str | None] = {}
    for k, v in phases.items():
        if not isinstance(v, dict):
            status_map[str(k)] = str(v)
            continue
        pid = str(k)
        status_map[pid] = str(v.get("status") or "")
        cause_map[pid] = v.get("cause") if v.get("cause") else None
        last_remediation[pid] = v.get("lastRemediationAt")
        stabilize_pass[pid] = v.get("stabilizePassId")
    remediation = state.get("remediationAttempts") or {}
    verify_remediation = state.get("verifyRemediationAttempts") or {}
    status_reemit = state.get("statusReemitAttempts") or {}
    payload = {
        "verdict": state.get("verdict"),
        "nextAction": state.get("nextAction"),
        "currentWave": state.get("currentWave"),
        "phaseStatuses": dict(sorted(status_map.items())),
        "phaseCauses": dict(sorted(cause_map.items())),
        "remediationAttempts": dict(sorted((str(k), int(v)) for k, v in remediation.items())),
        "verifyRemediationAttempts": dict(
            sorted((str(k), int(v)) for k, v in verify_remediation.items())
        ),
        "statusReemitAttempts": dict(sorted((str(k), int(v)) for k, v in status_reemit.items())),
        "lastRemediationAt": dict(sorted(last_remediation.items())),
        "stabilizePassId": dict(sorted(stabilize_pass.items())),
        "mergeQueueLength": len(state.get("mergeQueue") or []),
        "mergeEnqueueAttempts": dict(sorted((str(k), int(v)) for k, v in (state.get("mergeEnqueueAttempts") or {}).items())),
        "mergeJournalPresent": state.get("mergeJournal") is not None,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def record_budget_tick(root: Path, state: dict[str, Any], next_action: str) -> None:
    init_budget_counters(state)
    state["driverIterationCount"] = int(state.get("driverIterationCount", 0)) + 1
    counters = state.setdefault(
        "budgetCounters",
        {"proposalOverheadCount": 0, "executionIterationCount": 0},
    )
    if next_action in PROPOSAL_OVERHEAD_ACTIONS:
        counters["proposalOverheadCount"] = int(counters.get("proposalOverheadCount", 0)) + 1
    else:
        counters["executionIterationCount"] = int(
            counters.get("executionIterationCount", 0)
        ) + 1
        stall_cause = classify_deliver_stall_cause(
            root,
            state,
            next_action,
            phase_id=str(state.get("_stallPhaseId") or ""),
            worktree_name=state.get("_stallWorktreeName"),
        )
        progress_key = stall_progress_key(
            build_state_signature(state),
            next_action,
            stall_cause,
        )
        if progress_key == state.get("lastProgressKey"):
            state["noProgressStreak"] = int(state.get("noProgressStreak", 0)) + 1
        else:
            if int(state.get("noProgressStreak", 0)) > 0:
                supersede_stale_blockers(root)
            state["noProgressStreak"] = 0
            state["lastProgressKey"] = progress_key
        if stall_cause:
            state["lastStallCause"] = stall_cause
        else:
            state.pop("lastStallCause", None)


def plan_rejection_halt_cause(state: dict[str, Any]) -> str | None:
    log = state.get("planRejectionLog")
    if not isinstance(log, dict):
        return None
    halt = log.get("halt")
    if not isinstance(halt, dict):
        return None
    return str(halt.get("cause") or "conductor:plan-rejection-breaker")


def sync_plan_rejection_no_progress(state: dict[str, Any]) -> None:
    """Subscribe 022 planRejectionLog breaker into the no-progress surface (R22)."""
    cause = plan_rejection_halt_cause(state)
    if not cause:
        return
    threshold = DEFAULT_NO_PROGRESS_THRESHOLD
    state["noProgressStreak"] = max(int(state.get("noProgressStreak", 0)), threshold)



def merge_queue_drain_preferred(state: dict[str, Any]) -> bool:
    """True when merge queue can drain without an open journal (PRD 072 R5)."""
    return bool(state.get("mergeQueue")) and not state.get("mergeJournal")


def _merge_queue_liveness_targets(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    merge_slugs = {
        str(entry.get("phaseSlug"))
        for entry in (state.get("mergeQueue") or [])
        if isinstance(entry, dict) and entry.get("phaseSlug")
    }
    targets: list[tuple[str, dict[str, Any]]] = []
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict):
            continue
        slug = str(meta.get("slug") or "")
        if meta.get("status") == "in-flight" or slug in merge_slugs:
            targets.append((str(pid), meta))
    return targets


def refresh_merge_queue_liveness_cas(
    root: Path,
    state: dict[str, Any],
    *,
    max_attempts: int = 3,
) -> bool:
    """Refresh livenessAt/updatedAt for queued in-flight phases; never rewrite startedAt (R5)."""
    expected_at = str(state.get("updatedAt") or "")
    for _ in range(max_attempts):
        fresh = load_state(root)
        if expected_at and str(fresh.get("updatedAt") or "") != expected_at:
            state.update(fresh)
            expected_at = str(fresh.get("updatedAt") or "")
            continue
        now = utc_now()
        changed = False
        for _pid, meta in _merge_queue_liveness_targets(fresh):
            started = meta.get("startedAt")
            if meta.get("livenessAt") != now or meta.get("updatedAt") != now:
                meta["livenessAt"] = now
                meta["updatedAt"] = now
                if started is not None:
                    meta["startedAt"] = started
                changed = True
        if not changed:
            state.update(fresh)
            return True
        fresh["updatedAt"] = now
        save_state(root, fresh)
        state.update(fresh)
        return True
    return False


def phase_watchdog_stale(meta: dict[str, Any], timeout_seconds: float) -> bool:
    """Phase timeout uses startedAt; recent livenessAt suppresses false stuck (R5)."""
    liveness = meta.get("livenessAt")
    if isinstance(liveness, str):
        liveness_age = age_seconds(liveness)
        if liveness_age is not None and liveness_age <= timeout_seconds:
            return False
    started = meta.get("startedAt")
    if not isinstance(started, str):
        started = meta.get("updatedAt")
    if not isinstance(started, str):
        return False
    age = age_seconds(started)
    return age is not None and age > timeout_seconds


def remediate_pending_for_state(root: Path, state: dict[str, Any]) -> bool:
    """True when a blocked phase still has remediation budget (R31 — no-progress deferral)."""
    for _pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict) or meta.get("status") != "blocked":
            continue
        cause = str(meta.get("cause") or "")
        if not cause.startswith("verify:"):
            continue
        attempts_key = (
            "verifyRemediationAttempts"
            if cause.startswith("verify:environmental")
            else "remediationAttempts"
        )
        attempts = state.get(attempts_key) or {}
        count = int(attempts.get(str(_pid), 0))
        if count < remediation_max(root):
            return True
    return False


def refresh_batch_integration_head(root: Path, state: dict[str, Any]) -> None:
    """Atomically refresh batchIntegrationHead when batch queue active (R34)."""
    if not (state.get("mergeQueue") or state.get("mergeJournal")):
        return
    head = integration_branch_head(root, state)
    if head:
        state["batchIntegrationHead"] = head



def check_budget_halt(root: Path, state: dict[str, Any]) -> str | None:
    init_budget_counters(state)
    sync_plan_rejection_no_progress(state)

    rejection = plan_rejection_halt_cause(state)
    if rejection:
        return rejection

    counters = state.get("budgetCounters") or {}
    execution_count = int(counters.get("executionIterationCount", 0))
    if execution_count >= max_iterations(root):
        return "conductor:max-iterations-exceeded"

    max_mins = max_run_minutes(root)
    if max_mins is not None:
        started = state.get("runStartedAt")
        if isinstance(started, str):
            age = age_seconds(started)
            if age is not None and age > max_mins * 60:
                return "conductor:max-run-minutes-exceeded"

    if int(state.get("noProgressStreak", 0)) >= no_progress_threshold(root):
        stall = classify_deliver_stall_cause(
            root,
            state,
            str(state.get("nextAction") or ""),
            phase_id=str(state.get("_stallPhaseId") or ""),
            worktree_name=state.get("_stallWorktreeName"),
        )
        if is_differentiated_stall(stall):
            return None
        if remediate_pending_for_state(root, state):
            return None
        try:
            import failure_signature_record_lib as fsr

            fsr.maybe_record_no_progress(root, state)
        except Exception:
            pass
        return "conductor:no-progress"

    return None


def is_budget_halt(cause: str) -> bool:
    return cause in BUDGET_HALT_CAUSES or cause.startswith("conductor:")


def preserve_merge_queue_on_halt(state: dict[str, Any]) -> None:
    """Clear abandoned merge journal while keeping queue replayable (R22)."""
    journal = state.get("mergeJournal")
    if not isinstance(journal, dict):
        return
    phase_slug = str(journal.get("phase") or "")
    queue = list(state.get("mergeQueue") or [])
    if phase_slug:
        existing = next(
            (entry for entry in queue if entry.get("phaseSlug") == phase_slug),
            None,
        )
        if existing is None:
            queue.insert(
                0,
                {
                    "phaseSlug": phase_slug,
                    "head": journal.get("head"),
                    "recoveredFromJournal": True,
                },
            )
        elif existing.get("head") is None and journal.get("head"):
            existing["head"] = journal.get("head")
    state["mergeQueue"] = queue
    state["mergeJournal"] = None


def clean_consolidated_halt(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    cause: str,
) -> dict[str, Any]:
    from wave_merge import clear_open_journal_if_merged
    from wave_state import append_log as state_append_log, scoped_paths

    state.update(clear_open_journal_if_merged(root, state))
    preserve_merge_queue_on_halt(state)
    state["verdict"] = "blocked"
    state["cause"] = cause
    save_state(root, state)

    target = (state.get("target") or {}).get("branch") or (plan.get("target") or {}).get(
        "branch"
    )
    lock_released = False
    if target:
        lock_path = scoped_paths(root, str(target))["lock"]
        if lock_path.is_file():
            meta: dict[str, Any] = {}
            try:
                raw = lock_path.read_text(encoding="utf-8").strip()
                if raw:
                    meta = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                meta = {}
            lock_path.unlink(missing_ok=True)
            state_append_log(root, {"event": "lock-release", "target": meta.get("target") or target})
            lock_released = True

    path = write_blocker_report(root, state, cause)
    persist_cursor(
        root,
        state,
        "halt-blocked",
        blockerReport=str(path),
        budgetHalt=True,
        lockReleased=lock_released,
    )
    return {
        "executed": "halt-blocked",
        "cause": cause,
        "blockerReport": str(path),
        "budgetHalt": True,
        "lockReleased": lock_released,
        "mergeQueueLength": len(state.get("mergeQueue") or []),
        "mergeEnqueueAttempts": dict(sorted((str(k), int(v)) for k, v in (state.get("mergeEnqueueAttempts") or {}).items())),
        "mergeJournalPresent": state.get("mergeJournal") is not None,
    }


def parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_seconds(ts: str) -> float | None:
    dt = parse_ts(ts)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def append_log(root: Path, entry: dict[str, Any], state: dict[str, Any] | None = None) -> None:
    target = target_branch_from_state(state) if state else None
    state_append_log(root, entry, target=target)


def load_plan(root: Path) -> dict[str, Any]:
    path = root / PLAN_PATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(root: Path, task_list: str | None = None) -> dict[str, Any]:
    return load_deliver_state(root, task_list=task_list)


def save_state(root: Path, state: dict[str, Any]) -> None:
    save_deliver_state(root, state)



def sync_terminal_state(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Canonical repo-root state read before terminal deliver actions (PRD 049 R4, 069 R3)."""
    synced = ensure_canonical_state_synced(root, state_hint=state)
    if synced:
        state.clear()
        state.update(synced)
    return state


def manual_living_doc_reconcile_suggestion(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Operator-facing living-doc reconcile suggestion with in-flight cwd guard (PRD 049 R3)."""
    import deliver_cwd_guard

    guard = deliver_cwd_guard.check()
    orch = orchestrator_worktree_path(root, state)
    orch_flag = f" --orchestrator-worktree {orch}" if orch else ""
    command = f"python3 scripts/wave.py living-docs reconcile --commit{orch_flag}"
    payload: dict[str, Any] = {
        "command": command,
        "orchestratorWorktree": str(orch) if orch else None,
    }
    if guard.get("verdict") == "fail":
        payload["guardBlocked"] = True
        payload["remediation"] = guard.get("remediation")
        payload["error"] = guard.get("error")
    return payload


def cmd_manual_living_doc_reconcile(root: Path, args: list[str]) -> None:
    """Run guarded manual living-doc reconcile from deliver-loop suggestions."""
    import deliver_cwd_guard

    deliver_cwd_guard.enforce()
    state = load_state(root)
    orch = orchestrator_worktree_path(root, state)
    living_args = ["reconcile", "--commit"]
    if orch is not None:
        living_args.extend(["--orchestrator-worktree", str(orch)])
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_living_docs.py"), str(root), *living_args],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "living-doc reconcile failed", exit_code=proc.returncode)
    emit(json.loads(proc.stdout) if proc.stdout.strip().startswith("{") else {"raw": proc.stdout})


def ensure_driver_fields(state: dict[str, Any]) -> None:
    state.setdefault("currentWave", 1)
    state.setdefault("nextAction", "plan")
    state.setdefault("remediationAttempts", {})
    state.setdefault("phaseWorktrees", {})
    state.setdefault("driverHeartbeatAt", utc_now())
    init_budget_counters(state)


def phase_status_map(state: dict[str, Any]) -> dict[str, str]:
    phases = state.get("phases") or {}
    return {
        str(k): (v.get("status", "pending") if isinstance(v, dict) else str(v))
        for k, v in phases.items()
    }


def deps_satisfied(phase_id: str, plan: dict[str, Any], statuses: dict[str, str]) -> bool:
    for edge in plan.get("edges") or []:
        if str(edge.get("to")) == phase_id:
            dep = str(edge.get("from", ""))
            if statuses.get(dep) not in MERGED_PHASE_STATUSES:
                return False
    return True


def wave_phase_ids(plan: dict[str, Any], wave_num: int) -> list[str]:
    waves = plan.get("waves") or []
    if wave_num < 1 or wave_num > len(waves):
        return []
    return [str(p) for p in waves[wave_num - 1]]


def all_phases_merged(state: dict[str, Any]) -> bool:
    statuses = phase_status_map(state)
    return bool(statuses) and all(s in MERGED_PHASE_STATUSES for s in statuses.values())


def in_flight_count(statuses: dict[str, str], wave_ids: list[str]) -> int:
    return sum(1 for pid in wave_ids if statuses.get(pid) == "in-flight")




def phase_worktree_provisioned(state: dict[str, Any], phase_id: str) -> bool:
    """dispatch-ship requires phaseWorktrees path on disk (R8)."""
    wt = (state.get("phaseWorktrees") or {}).get(str(phase_id))
    if not isinstance(wt, dict):
        return False
    path = wt.get("path")
    return bool(path) and Path(str(path)).is_dir()


def phase_worktree_name_for(state: dict[str, Any], plan: dict[str, Any], phase_id: str) -> str | None:
    item = item_for_phase(plan, phase_id) or {}
    slug = item.get("slug") or phase_id
    target_slug = slug_from_target((plan.get("target") or {}).get("branch", "feat/x"))
    return f"{target_slug}-phase-{slug}"


def slug_from_target(target_branch: str) -> str:
    if "/" not in target_branch:
        return target_branch
    return target_branch.split("/", 1)[1]

def phase_dispatch_payload(
    plan: dict[str, Any], phase_id: str
) -> dict[str, Any]:
    item = item_for_phase(plan, phase_id) or {}
    return {
        "phaseId": phase_id,
        "phaseSlug": item.get("slug"),
        "branch": item.get("branch"),
    }


def runnable_pending_phases(
    wave_ids: list[str],
    statuses: dict[str, str],
    plan: dict[str, Any],
) -> list[str]:
    ready: list[str] = []
    for pid in sorted(wave_ids):
        if statuses.get(pid) != "pending":
            continue
        if not deps_satisfied(pid, plan, statuses):
            continue
        ready.append(pid)
    return ready


def mark_background_task_blocked(
    state: dict[str, Any], phase_id: str, cause: str
) -> None:
    phases = state.setdefault("phases", {})
    meta = phases.get(phase_id)
    if not isinstance(meta, dict):
        return
    meta["status"] = "blocked"
    meta["cause"] = cause
    meta["updatedAt"] = utc_now()


def check_background_task_failures(
    root: Path, state: dict[str, Any], wave_ids: list[str]
) -> str | None:
    timeout_min = background_task_timeout_minutes(root)
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        if not meta.get("backgroundDispatchedAt"):
            continue
        slug = meta.get("slug", pid)
        status_path, status = read_phase_status_optional(root, slug, state)
        if status is not None and status.get("verdict") in VALID_STATUS_VERDICTS:
            continue
        started = meta.get("backgroundDispatchedAt") or meta.get("startedAt")
        if isinstance(started, str):
            age = age_seconds(started)
            if age is not None and age > timeout_min * 60:
                mark_background_task_blocked(
                    state,
                    pid,
                    f"background-task-timeout:{pid}",
                )
                save_state(root, state)
                return f"background-task-timeout:{pid}"
    return None


def merge_ready_in_flight_phases(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    wave_ids: list[str],
) -> list[dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", pid)
        status_path, status = read_phase_status_optional(root, slug, state)
        if status is None:
            continue
        if status.get("verdict") != "merge-ready-green":
            continue
        ok_shape, _shape_cause = validate_terminal_status_shape(status, root)
        if not ok_shape:
            continue
        phase_branch = meta.get("branch")
        if not phase_branch:
            continue
        expected = phase_branch_head_optional(root, state, slug, str(phase_branch))
        if not expected:
            continue
        ok_sha, _sha_cause = check_status_sha(status, expected)
        if not ok_sha:
            continue
        pr_number = resolve_pr_number(root, state, slug, status, str(phase_branch))
        authorized, _evidence = live_host_evidence_ok(root, status, expected, pr_number)
        if not authorized:
            continue
        ok, _cause = tasks_currency_ok(root, state, plan)
        if not ok:
            continue
        ok, _cause = phase_acceptance_ok(root, state, plan, str(pid), str(slug))
        if not ok:
            continue
        ok, _cause = gap_check_gate_ok(root, state, plan, str(slug))
        if not ok:
            continue
        ready.append({"phaseId": pid, "phaseSlug": slug})
    return ready


def in_flight_wave_phases(wave_ids: list[str], statuses: dict[str, str]) -> list[str]:
    return [pid for pid in sorted(wave_ids) if statuses.get(pid) == "in-flight"]


def phase_has_validated_terminal(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    phase_id: str,
) -> bool:
    meta = (state.get("phases") or {}).get(phase_id, {})
    if not isinstance(meta, dict) or meta.get("status") != "in-flight":
        return True
    slug = str(meta.get("slug") or phase_id)
    _, status = read_phase_status_optional(root, slug, state)
    if status is None:
        return False
    if status.get("verdict") == "blocked":
        return status_is_consumable_terminal(status)
    if status.get("verdict") != "merge-ready-green":
        return False
    ok_shape, _ = validate_terminal_status_shape(status, root)
    if not ok_shape:
        return False
    phase_branch = meta.get("branch")
    if not phase_branch:
        return False
    expected = phase_branch_head_optional(root, state, slug, str(phase_branch))
    if not expected:
        return False
    ok_sha, _ = check_status_sha(status, expected)
    if not ok_sha:
        return False
    pr_number = resolve_pr_number(root, state, slug, status, str(phase_branch))
    authorized, _ = live_host_evidence_ok(root, status, expected, pr_number)
    if not authorized:
        return False
    ok, _ = tasks_currency_ok(root, state, plan)
    if not ok:
        return False
    ok, _ = phase_acceptance_ok(root, state, plan, phase_id, slug)
    if not ok:
        return False
    ok, _ = gap_check_gate_ok(root, state, plan, slug)
    return ok


def batch_in_flight_all_terminal(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    wave_ids: list[str],
    statuses: dict[str, str],
) -> bool:
    in_flight = in_flight_wave_phases(wave_ids, statuses)
    if len(in_flight) <= 1:
        return True
    return all(phase_has_validated_terminal(root, state, plan, pid) for pid in in_flight)


def integration_branch_head(root: Path, state: dict[str, Any]) -> str | None:
    target = (state.get("target") or {}).get("branch")
    if not target:
        return None
    orch = state.get("orchestratorWorktree") or {}
    wt_raw = orch.get("path")
    wt = Path(str(wt_raw)) if wt_raw else root
    if not wt.is_dir():
        wt = root
    proc = subprocess.run(
        ["git", "-C", str(wt), "rev-parse", str(target)],
        text=True,
        capture_output=True,
    )
    head = proc.stdout.strip()
    return head if proc.returncode == 0 and head else None


def batch_integration_head_halt(
    root: Path, state: dict[str, Any]
) -> dict[str, Any] | None:
    frozen = state.get("batchIntegrationHead")
    if not isinstance(frozen, str) or not frozen:
        return None
    current = integration_branch_head(root, state)
    if current and current != frozen:
        return {
            "action": "halt-blocked",
            "cause": "batch-integration-head-moved",
            "batchIntegrationHead": frozen,
            "currentIntegrationHead": current,
            "resume": True,
        }
    return None


def clear_batch_integration_head_if_idle(state: dict[str, Any]) -> None:
    if not state.get("mergeQueue") and not state.get("mergeJournal"):
        state.pop("batchIntegrationHead", None)


def in_flight_merge_halt(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    wave_ids: list[str],
) -> dict[str, Any] | None:
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", pid)
        status_path, status = read_phase_status_optional(root, slug, state)
        if status is None:
            continue
        if status.get("verdict") != "merge-ready-green":
            continue
        ok_shape, shape_cause = validate_terminal_status_shape(status, root)
        if not ok_shape:
            return {
                "action": "halt-blocked",
                "cause": shape_cause or "phase-status:invalid",
                "resume": True,
            }
        phase_branch = meta.get("branch")
        if phase_branch:
            expected = phase_branch_head_optional(root, state, slug, str(phase_branch))
            if expected:
                ok_sha, sha_cause = check_status_sha(status, expected)
                if not ok_sha:
                    return {
                        "action": "halt-blocked",
                        "cause": sha_cause or "phase-status:stale",
                        "resume": True,
                    }
        ok, cause = tasks_currency_ok(root, state, plan)
        if not ok:
            return {
                "action": "halt-blocked",
                "cause": cause,
                "resume": True,
                "livingDocReconcile": manual_living_doc_reconcile_suggestion(root, state),
            }
        ok, cause = phase_acceptance_ok(root, state, plan, str(pid), str(slug))
        if not ok:
            return {
                "action": "halt-blocked",
                "cause": cause,
                "resume": True,
            }
        ok, cause = gap_check_gate_ok(root, state, plan, str(slug))
        if not ok:
            return {
                "action": "halt-blocked",
                "cause": cause,
                "resume": True,
            }
    return None




def phase_worktree_path(state: dict[str, Any], phase_id: str) -> Path | None:
    entry = (state.get("phaseWorktrees") or {}).get(phase_id, {})
    if isinstance(entry, dict) and entry.get("path"):
        return Path(str(entry["path"]))
    return None


def ship_loop_env_for_phase(state: dict[str, Any], phase_id: str, slug: str) -> dict[str, str]:
    return {
        "SW_PHASE_MODE": "1",
        "SW_PHASE_SLUG": slug,
        "SW_RUN_DIR": f".cursor/sw-deliver-runs/{slug}",
        "SW_TASK_LIST": str(state.get("source_task_list") or ""),
        "SW_PHASE_ID": str(phase_id),
        "PYTHONPATH": "scripts",
    }


def run_ship_loop_drive(
    worktree: Path,
    phase_slug: str,
    env: dict[str, str],
    *,
    max_ticks: int = 64,
) -> tuple[int, dict[str, Any]]:
    cmd = [
        sys.executable,
        str(worktree / "scripts" / "ship_loop.py"),
        str(worktree),
        "drive",
        "--phase",
        phase_slug,
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(worktree),
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )
    raw = (proc.stdout or "").strip()
    if not raw:
        return proc.returncode or 2, {
            "verdict": "fail",
            "error": "ship-loop:empty-output",
            "stderr": (proc.stderr or "")[-500:],
        }
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return 2, {
            "verdict": "fail",
            "error": "ship-loop:invalid-json",
            "stdout": raw[-500:],
            "stderr": (proc.stderr or "")[-500:],
        }
    if proc.returncode != 0 and data.get("verdict") not in ("blocked",):
        data.setdefault("verdict", "fail")
    return proc.returncode, data


def execute_dispatch_ship(
    root: Path,
    state: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, Any]:
    pid = str(step.get("phaseId", ""))
    slug = str(step.get("phaseSlug") or pid)
    meta = (state.get("phases") or {}).get(pid, {})
    if not isinstance(meta, dict):
        fail("dispatch-ship missing phase meta", exit_code=2)
    lease_ec, lease_data = acquire_inline_dispatch_lease(root, state, pid, meta)
    if lease_ec != 0:
        fail_payload(lease_data, "dispatch-ship lease acquire failed", lease_ec)
    mark_phases_in_flight(state, [pid], background=False)
    wt = phase_worktree_path(state, pid)
    if wt is None or not wt.is_dir():
        fail("dispatch-ship missing phase worktree path", exit_code=20, phaseId=pid)
    env = ship_loop_env_for_phase(state, pid, slug)
    ec, drive = run_ship_loop_drive(wt, slug, env)
    out: dict[str, Any] = {
        "executed": "dispatch-ship",
        "phaseId": pid,
        "phaseSlug": slug,
        "shipLoop": drive,
    }
    if drive.get("awaitAgent") or (
        isinstance(drive.get("note"), str)
        and "deferred to agent ship chain" in drive["note"]
    ):
        out["awaitAgent"] = True
        out["shipStep"] = drive.get("step")
        out["shipContract"] = drive.get("contract")
        state["shipLoopAwait"] = {
            "phaseId": pid,
            "phaseSlug": slug,
            "step": drive.get("step"),
            "contract": drive.get("contract"),
        }
        save_state(root, state)
        return out
    if drive.get("complete"):
        out["shipComplete"] = True
        return out
    if drive.get("verdict") == "blocked":
        fail_payload(drive, "ship-loop blocked", 20)
    if ec != 0 or drive.get("verdict") == "fail":
        fail_payload(drive, "ship-loop drive failed", ec or 20)
    return out


def execute_dispatch_batch(
    root: Path,
    state: dict[str, Any],
    step: dict[str, Any],
) -> dict[str, Any]:
    phase_ids = [str(p) for p in step.get("phaseIds") or []]
    mark_phases_in_flight(state, phase_ids, background=True)
    save_state(root, state)
    return {
        "executed": "dispatch-batch",
        "phaseIds": phase_ids,
        "awaitAgent": True,
        "note": "background batch — phase-scoped executor runs ship-loop driver",
    }


def mark_phases_in_flight(
    state: dict[str, Any], phase_ids: list[str], *, background: bool = False
) -> None:
    phases = state.setdefault("phases", {})
    now = utc_now()
    for pid in phase_ids:
        meta = phases.get(pid)
        if not isinstance(meta, dict):
            continue
        meta["status"] = "in-flight"
        meta["startedAt"] = meta.get("startedAt") or now
        if background:
            meta["backgroundDispatchedAt"] = now
        else:
            meta.pop("backgroundDispatchedAt", None)
            meta["inlineDispatchedAt"] = now
        phases[pid] = meta


def phase_lease_branches(
    state: dict[str, Any], meta: dict[str, Any]
) -> tuple[str, str] | None:
    integration = (state.get("target") or {}).get("branch")
    phase_branch = meta.get("branch")
    if not integration or not phase_branch:
        return None
    return str(integration), str(phase_branch)


def inline_dispatch_lease_held_live(
    root: Path, state: dict[str, Any], meta: dict[str, Any]
) -> bool:
    branches = phase_lease_branches(state, meta)
    if not branches:
        return bool(meta.get("inlineDispatchedAt"))
    integration, phase_branch = branches
    ec, data = run_wave(
        root,
        "ship-lease",
        "status",
        "--integration",
        integration,
        "--phase-branch",
        phase_branch,
    )
    if ec != 0:
        return bool(meta.get("inlineDispatchedAt"))
    if not data.get("held"):
        return False
    return bool(data.get("live"))


def acquire_inline_dispatch_lease(
    root: Path, state: dict[str, Any], phase_id: str, meta: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    branches = phase_lease_branches(state, meta)
    if not branches:
        return 0, {}
    integration, phase_branch = branches
    slug = str(meta.get("slug") or phase_id)
    return run_wave(
        root,
        "ship-lease",
        "acquire",
        "--integration",
        integration,
        "--phase-branch",
        phase_branch,
        "--phase-slug",
        slug,
    )


def release_inline_dispatch_lease(
    root: Path, state: dict[str, Any], meta: dict[str, Any]
) -> None:
    branches = phase_lease_branches(state, meta)
    if not branches:
        return
    integration, phase_branch = branches
    run_wave(
        root,
        "ship-lease",
        "release",
        "--integration",
        integration,
        "--phase-branch",
        phase_branch,
    )


def check_watchdog(root: Path, state: dict[str, Any]) -> str | None:
    hb = state.get("driverHeartbeatAt")
    if isinstance(hb, str):
        age = age_seconds(hb)
        if age is not None and age > DRIVER_STALE_SECONDS:
            return "driver-heartbeat-stale"
    timeout_min = phase_timeout_minutes(root)
    timeout_seconds = timeout_min * 60
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict):
            continue
        if meta.get("status") != "in-flight":
            continue
        if phase_watchdog_stale(meta, timeout_seconds):
            return f"phase-timeout:{pid}"
    return None


def item_for_phase(plan: dict[str, Any], phase_id: str) -> dict[str, Any] | None:
    for item in plan.get("items") or []:
        if str(item.get("id")) == phase_id:
            return item
    return None


def task_list_from(state: dict[str, Any], plan: dict[str, Any]) -> str | None:
    raw = state.get("source_task_list") or plan.get("source_task_list")
    return str(raw) if raw else None


def trunk_base_persisted(root: Path) -> bool:
    path = root / ".cursor" / "sw-base-state.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    trunk = data.get("trunkBase")
    return isinstance(trunk, dict) and bool(trunk.get("name")) and bool(trunk.get("sha"))


def run_resolve_capture(root: Path) -> tuple[int, dict[str, Any]]:
    script = resolve_script(root, "resolve-base-branch.py")
    if not script.is_file():
        return 2, {"verdict": "fail", "error": "resolve-base-branch.py missing"}
    proc = subprocess.run(
        [sys.executable, str(script), "capture"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {"verdict": "fail", "error": proc.stderr.strip() or proc.stdout.strip()}
    return proc.returncode, data


def canonical_task_list_path(root: Path, raw: str) -> str:
    path = Path(raw)
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)




def check_deliver_hang_desync(root: Path, state: dict[str, Any]) -> str | None:
    """Fail-closed hang/desync causes before no-progress (PRD 063 R5)."""
    orch = (state.get("orchestratorWorktree") or {}).get("path")
    if isinstance(orch, str) and orch.strip():
        try:
            orch_path = Path(orch)
            if (
                ".sw-worktrees" in str(orch_path)
                and orch_path.is_dir()
                and orch_path.resolve() != root.resolve()
            ):
                return "deliver:orchestrator-cwd-skew"
        except OSError:
            return "deliver:orchestrator-path-invalid"
    try:
        sync_canonical_state_read(root, state_hint=state)
    except SystemExit:
        return "deliver:canonical-state-desync"
    except Exception:
        pass
    timeout_s = DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN * 60
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        dispatched = meta.get("inlineDispatchedAt")
        if not dispatched:
            continue
        slug = str(meta.get("slug") or pid)
        _, status = read_phase_status_optional(root, slug, state)
        if status_is_consumable_terminal(status):
            continue
        age = age_seconds(str(dispatched))
        if age is not None and age > timeout_s:
            return f"deliver:dispatch-stale-no-terminal:{pid}"
    return None


def assert_driver_adopt_gate(
    state: dict[str, Any], loop_args: list[str], *, fresh_seconds: int = 120
) -> None:
    """Refuse double-drive when heartbeat is fresh unless --self-wake (PRD 063 R6)."""
    if has_flag(loop_args, "--self-wake") or has_flag(loop_args, "--dry-run"):
        return
    if state.get("verdict") != "running" or not state.get("phases"):
        return
    hb = state.get("driverHeartbeatAt")
    if not isinstance(hb, str):
        return
    age = age_seconds(hb)
    if age is not None and age < fresh_seconds:
        fail(
            "driver-heartbeat-fresh-double-adopt",
            exit_code=20,
            halt="double-drive",
            remediation="wait for driver heartbeat to go stale or use self-wake continuation",
            driverHeartbeatAt=hb,
            ageSeconds=age,
        )


def assert_run_identity(
    root: Path, state: dict[str, Any], task_list: str | None, loop_args: list[str]
) -> None:
    """Refuse a new run when durable state belongs to a different task list (R30, R43)."""
    if not task_list or not state.get("phases"):
        return
    if state.get("verdict") not in (None, "running"):
        return
    existing = state.get("source_task_list")
    if not existing:
        return
    if canonical_task_list_path(root, str(existing)) == canonical_task_list_path(root, task_list):
        return
    if has_flag(loop_args, "--reset"):
        return
    fail(
        "stale run-state from a different source_task_list/prd_number",
        exit_code=20,
        halt="stale-state",
        remediation="bash scripts/wave.py deliver-loop --reset --task-list <path> or remove scoped .cursor/sw-deliver-state.<slug>.json",
    )


def _target_merge_detected(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_compound.py"), str(root), "completion", "check-merge"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    try:
        data = json.loads(proc.stdout or "{}")
        return {
            "merged": bool(data.get("merged")),
            "status": data.get("status"),
            "detail": data.get("detail"),
        }
    except json.JSONDecodeError:
        return {"merged": False, "reason": "check-merge-failed"}




def phase_acceptance_ok(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    phase_id: str,
    phase_slug: str,
) -> tuple[bool, str | None]:
    from phase_acceptance_gate import check_phase_acceptance

    return check_phase_acceptance(root, state, plan, phase_id, phase_slug)


def gap_check_gate_ok(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    phase_slug: str,
) -> tuple[bool, str | None]:
    if not task_list_from(state, plan):
        return True, None
    import importlib.util

    gate_path = SCRIPT_DIR / "gap-check-gate.py"
    spec = importlib.util.spec_from_file_location("gap_check_gate", gate_path)
    if spec is None or spec.loader is None:
        return False, "gap-check-gate-missing"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.deliver_gap_check_ok(root, phase_slug, require_status=True)

def tasks_currency_ok(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> tuple[bool, str | None]:
    resolved = resolve_currency_check(root, state, plan)
    if resolved == (None, None):
        return True, None
    check_root, tasks_file = resolved
    state_py = SCRIPT_DIR / "wave_state.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(state_py),
            str(check_root),
            "ledger",
            "check",
            "--tasks-file",
            tasks_file,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, None
    return False, "tasks-currency-divergence"



def effective_wave_plan(state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Single source of truth: persisted waveBatchingPlan overlays frozen deliver plan waves."""
    batching = state.get("waveBatchingPlan")
    if isinstance(batching, dict) and batching.get("waves"):
        merged = dict(plan)
        merged["waves"] = batching.get("waves")
        if batching.get("parallelCeiling"):
            merged["parallelCeiling"] = batching.get("parallelCeiling")
        if batching.get("planPolicy"):
            merged["planPolicy"] = batching.get("planPolicy")
        return merged
    return plan


def phase_run_dir_for_slug(root: Path, slug: str) -> Path:
    return root / ".cursor" / "sw-deliver-runs" / slug


def mechanical_phase_plan(
    root: Path, phase_id: str, slug: str, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    recorded_parent = None
    if state:
        batching = state.get("waveBatchingPlan")
        if isinstance(batching, dict):
            recorded_parent = batching
    plan = phase_fallback_canonical_chain(root, "ship", phase_id, recorded_parent=recorded_parent)
    task_list = str(state.get("source_task_list") or "") if state else ""
    if task_list:
        from execute_ship import adapt_phase_plan_for_execute_tier
        plan = adapt_phase_plan_for_execute_tier(root, plan, task_list=task_list, phase_id=phase_id)
    return plan


def dispatch_or_phase_plan_entry(
    state: dict[str, Any], plan: dict[str, Any], phase_id: str, *, note: str | None = None
) -> dict[str, Any]:
    item = item_for_phase(plan, phase_id) or {}
    slug = item.get("slug") or phase_id
    if not phase_worktree_provisioned(state, phase_id):
        return {
            "action": "provision-phase",
            "phaseId": phase_id,
            "phaseSlug": slug,
            "resume": True,
            "note": "dispatch-ship refused until phaseWorktrees records provisioned path (R8)",
        }
    if needs_phase_plan_proposal(state, phase_id):
        return {
            "action": "phase-plan-entry",
            "phaseId": phase_id,
            "phaseSlug": slug,
            "resume": True,
        }
    payload = {
        "action": "dispatch-ship",
        "phaseId": phase_id,
        "phaseSlug": slug,
        "resume": True,
    }
    if note:
        payload["note"] = note
    return payload


def compute_next_action(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    ensure_driver_fields(state)
    budget_cause = check_budget_halt(root, state)
    if budget_cause:
        return {
            "action": "halt-blocked",
            "cause": budget_cause,
            "budgetHalt": True,
            "resume": True,
        }
    verdict = state.get("verdict", "running")

    if verdict in ("complete", "blocked", "rejected"):
        return {"action": "terminal", "verdict": verdict, "resume": True}

    if not plan:
        return {"action": "plan", "resume": bool(state.get("phases"))}

    if plan.get("mode") != "phase":
        fail("deliver-loop requires phase-mode plan", exit_code=2)

    if not state.get("phases"):
        return {"action": "state-init", "resume": False}

    if not trunk_base_persisted(root) and not state.get("baseCapture"):
        return {"action": "base-capture", "resume": True}

    if (
        not state.get("specSeed")
        and task_list_from(state, plan)
        and not state.get("orchestratorWorktree")
    ):
        return {
            "action": "spec-seed",
            "taskList": task_list_from(state, plan),
            "resume": True,
        }

    target = (plan.get("target") or {}).get("branch") or (state.get("target") or {}).get(
        "branch"
    )
    if not target:
        fail("plan/state missing target branch")

    if all_phases_merged(state):
        completion = state.get("completion") or {}
        compound = state.get("compoundShip") or {}
        terminal_ship = state.get("terminalShip") or {}
        if completion.get("status") == "completed-pending-merge":
            merge_info = _target_merge_detected(root, state)
            if merge_info.get("merged"):
                return {
                    "action": "finalize-completion",
                    "cleanupSuggestion": "Run `/sw-cleanup` to prune merged branches and stale worktrees.",
                    "resume": True,
                }
            if compound.get("premergeDone"):
                return {
                    "action": "terminal-ship",
                    "note": "awaiting human merge — completion pending until merged",
                    "resume": True,
                }
        if terminal_autonomy_mode(root) == "supervised" and not state.get(
            "terminalCheckpointCompleted"
        ):
            needs_retro = not compound.get("premergeDone")
            needs_ship = terminal_ship.get("status") not in (
                "gate-green",
                "local-evidence",
            )
            if needs_retro or needs_ship:
                return {
                    "action": "terminal-checkpoint",
                    "resume": True,
                    "mode": "supervised",
                    "needsRetrospective": needs_retro,
                    "needsTerminalShip": needs_ship,
                    "note": "Single consolidated supervised terminal checkpoint (R10)",
                }
        if not compound.get("premergeDone"):
            return {"action": "retrospective", "resume": True}
        return {"action": "terminal-ship", "resume": True}

    effective_plan = effective_wave_plan(state, plan)

    if state.get("orchestratorWorktree") and not wave_plan_ready(state):
        return {"action": "wave-plan-persist", "resume": True}

    if not state.get("orchestratorWorktree"):
        if state.get("nextAction") in (None, "plan", "state-init"):
            return {"action": "lock-acquire", "target": target, "resume": True}
        return {"action": "orchestrator-provision", "target": target, "resume": True}

    statuses = phase_status_map(state)
    wave_num = int(state.get("currentWave") or 1)
    wave_ids = wave_phase_ids(effective_plan, wave_num)
    waves = effective_plan.get("waves") or []

    if wave_num > len(waves) and not wave_ids:
        if all_phases_merged(state):
            pass  # handled by terminal routing above
        elif statuses and all(
            statuses.get(pid) in (*MERGED_PHASE_STATUSES, "blocked", "rejected")
            for pid in statuses
        ):
            return {
                "action": "halt-blocked",
                "cause": "current-wave-overflow",
                "resume": True,
                "note": "currentWave past plan.waves — terminal degrade (R32)",
            }

    # Blocked phases awaiting remediation or halt (before watchdog — explicit blockers win)
    for pid in wave_ids:
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict):
            continue
        if meta.get("status") == "blocked":
            cause = str(meta.get("cause") or "")
            if cause.startswith("verify:"):
                history = meta.get("remediationCauseHistory") or []
                if (
                    isinstance(history, list)
                    and len(history) >= 2
                    and history[-1] == history[-2]
                ):
                    return {
                        "action": "halt-blocked",
                        "phaseId": pid,
                        "phaseSlug": meta.get("slug"),
                        "cause": "remediation-non-converging",
                        "resume": True,
                    }
            attempts_key = (
                "verifyRemediationAttempts"
                if cause.startswith("verify:environmental")
                else "remediationAttempts"
            )
            attempts = state.get(attempts_key) or {}
            count = int(attempts.get(str(pid), 0))
            max_attempts = remediation_max(root)
            if count < max_attempts:
                cause_class = (
                    "environmental"
                    if cause.startswith("verify:environmental")
                    else "regression"
                )
                if cause_class == "environmental" and merge_queue_drain_preferred(state):
                    continue
                if cause_class == "environmental":
                    return {
                        "action": "post-merge-verify-remediate",
                        "phaseId": pid,
                        "phaseSlug": meta.get("slug"),
                        "attempt": count + 1,
                        "maxAttempts": max_attempts,
                        "resume": True,
                        "causeClass": cause_class,
                    }
                return {
                    "action": "remediate",
                    "phaseId": pid,
                    "phaseSlug": meta.get("slug"),
                    "attempt": count + 1,
                    "maxAttempts": max_attempts,
                    "resume": True,
                    "causeClass": cause_class,
                }
            return {
                "action": "halt-blocked",
                "phaseId": pid,
                "phaseSlug": meta.get("slug"),
                "cause": "remediation-budget-exhausted",
                "resume": True,
            }

    bg_fail = check_background_task_failures(root, state, wave_ids)
    if bg_fail:
        return {
            "action": "halt-blocked",
            "cause": bg_fail,
            "resume": True,
            "watchdog": True,
        }

    desync = check_deliver_hang_desync(root, state)
    if desync:
        return {
            "action": "halt-blocked",
            "cause": desync,
            "resume": True,
            "desync": True,
        }

    if merge_queue_drain_preferred(state) or any(
        isinstance(meta, dict) and meta.get("postMergeVerifyPending")
        for meta in (state.get("phases") or {}).values()
    ):
        refresh_merge_queue_liveness_cas(root, state)

    watchdog = check_watchdog(root, state)
    if watchdog:
        return {
            "action": "halt-blocked",
            "cause": watchdog,
            "resume": True,
            "watchdog": True,
        }

    merge_halt = in_flight_merge_halt(root, state, plan, wave_ids)
    if merge_halt:
        return merge_halt

    batch_halt = batch_integration_head_halt(root, state)
    if batch_halt:
        return batch_halt

    if (state.get("mergeQueue") or []) and not state.get("mergeJournal"):
        return {"action": "merge-run-next", "resume": True}

    in_flight = in_flight_wave_phases(wave_ids, statuses)
    merge_ready = merge_ready_in_flight_phases(root, state, plan, wave_ids)
    batch_complete = batch_in_flight_all_terminal(root, state, plan, wave_ids, statuses)

    if len(in_flight) > 1 and merge_ready and not batch_complete:
        return {
            "action": "await-in-flight",
            "phaseIds": in_flight,
            "resume": True,
            "note": "whole-batch completion wait — no early merge (R10)",
        }

    if merge_ready and batch_complete:
        if len(merge_ready) > 1:
            return {
                "action": "collect-all-ready",
                "phases": merge_ready,
                "resume": True,
            }
        if len(merge_ready) == 1:
            entry = merge_ready[0]
            return {
                "action": "merge-enqueue",
                "phaseId": entry["phaseId"],
                "phaseSlug": entry["phaseSlug"],
                "resume": True,
            }

    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = str(meta.get("slug") or pid)
        _, status = read_phase_status_optional(root, slug, state)
        if status_is_consumable_terminal(status):
            continue
        is_stale, detail = detect_stuck_stale_phase(root, state, pid, meta)
        if not is_stale:
            continue
        attempts = state.get("statusReemitAttempts") or {}
        count = int(attempts.get(str(pid), 0))
        max_attempts = status_reemit_max(root)
        if count < max_attempts:
            return {
                "action": "canonical-reemit",
                "phaseId": pid,
                "phaseSlug": slug,
                "attempt": count + 1,
                "maxAttempts": max_attempts,
                "resume": True,
                "stuckStale": detail,
            }
        return {
            "action": "halt-blocked",
            "phaseId": pid,
            "phaseSlug": slug,
            "cause": "status-reemit-budget-exhausted",
            "resume": True,
        }

    awaiting: list[str] = []
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", "")
        status_path, status = read_phase_status_optional(root, slug, state)
        if status is not None:
            if status.get("verdict") == "blocked":
                return {
                    "action": "collect-status",
                    "phaseId": pid,
                    "phaseSlug": slug,
                    "resume": True,
                }
            if status.get("verdict") == "merge-ready-green":
                continue
        if meta.get("backgroundDispatchedAt"):
            awaiting.append(pid)
            continue
        if meta.get("inlineDispatchedAt") and inline_dispatch_lease_held_live(
            root, state, meta
        ):
            awaiting.append(pid)
            continue
        return dispatch_or_phase_plan_entry(
            state,
            plan,
            pid,
            note="awaiting /sw-ship --phase-mode in phase worktree",
        )

    if awaiting:
        return {
            "action": "await-in-flight",
            "phaseIds": awaiting,
            "resume": True,
            "note": "awaiting terminal status.json from background Tasks",
        }

    teardown_pending = [
        pid
        for pid in sorted(wave_ids)
        if statuses.get(pid) == "teardown-pending"
    ]
    if teardown_pending:
        pid = teardown_pending[0]
        meta = (state.get("phases") or {}).get(pid, {})
        return {
            "action": "phase-teardown-run",
            "phaseId": pid,
            "phaseSlug": meta.get("slug") if isinstance(meta, dict) else pid,
            "resume": True,
        }

    ceiling = parallel_ceiling(root)
    slots_used = in_flight_count(statuses, wave_ids)
    slots_free = max(0, ceiling - slots_used)
    runnable = runnable_pending_phases(wave_ids, statuses, plan)
    if runnable and slots_free > 0:
        worktrees = state.get("phaseWorktrees") or {}
        need_provision = [pid for pid in runnable if pid not in worktrees]
        if need_provision:
            pid = need_provision[0]
            item = item_for_phase(plan, pid)
            return {
                "action": "provision-phase",
                "phaseId": pid,
                "phaseSlug": (item or {}).get("slug"),
                "resume": True,
            }
        batch_ids = runnable[:slots_free]
        batch_phases = [phase_dispatch_payload(plan, pid) for pid in batch_ids]
        if len(batch_ids) >= 2:
            return {
                "action": "dispatch-batch",
                "phaseIds": batch_ids,
                "phases": batch_phases,
                "slotCount": len(batch_ids),
                "parallelCeiling": ceiling,
                "resume": True,
                "note": "spawn N background Tasks (run_in_background: true) — one per phase worktree",
            }
        pid = batch_ids[0]
        return dispatch_or_phase_plan_entry(state, plan, pid)

    # Pending runnable phases in current wave (legacy single-phase path)
    for pid in wave_ids:
        if statuses.get(pid) != "pending":
            continue
        if not deps_satisfied(pid, plan, statuses):
            continue
        worktrees = state.get("phaseWorktrees") or {}
        if pid not in worktrees:
            item = item_for_phase(plan, pid)
            return {
                "action": "provision-phase",
                "phaseId": pid,
                "phaseSlug": (item or {}).get("slug"),
                "resume": True,
            }
        return dispatch_or_phase_plan_entry(state, plan, pid)

    # Wave complete — advance or wait on blocked upstream elsewhere
    if wave_ids and all(
        statuses.get(pid) in (*MERGED_PHASE_STATUSES, "blocked", "rejected")
        for pid in wave_ids
    ):
        waves = plan.get("waves") or []
        if wave_num < len(waves):
            return {"action": "advance-wave", "fromWave": wave_num, "resume": True}
        if any(statuses.get(pid) == "blocked" for pid in wave_ids):
            return {"action": "halt-blocked", "cause": "wave-has-blocked-phases", "resume": True}

    return {
        "action": "await-in-flight",
        "resume": True,
        "note": "waiting for upstream phases or merge queue",
    }


def run_inflight_signal(root: Path, *args: str) -> tuple[int, dict[str, Any]]:
    script = resolve_script(root, "inflight-signal.py")
    if not script.is_file():
        return 2, {"verdict": "fail", "error": "inflight-signal.py missing"}
    proc = subprocess.run(
        [sys.executable, str(script), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    data: dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {"raw": proc.stdout.strip()}
    if proc.stderr.strip():
        data.setdefault("stderr", proc.stderr.strip())
    data["exitCode"] = proc.returncode
    return proc.returncode, data


def run_wave(root: Path, *args: str) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [*interpreter.probe().executable, str(resolve_script(root, "wave.py")), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    data: dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {"raw": proc.stdout.strip()}
    if proc.stderr.strip():
        data.setdefault("stderr", proc.stderr.strip())
    data["exitCode"] = proc.returncode
    return proc.returncode, data


def persist_cursor(root: Path, state: dict[str, Any], action: str, **extra: Any) -> None:
    state["nextAction"] = action
    state["driverHeartbeatAt"] = utc_now()
    for key, val in extra.items():
        state[key] = val
    save_state(root, state)
    entry: dict[str, Any] = {"event": "driver-transition", "nextAction": action, **extra}
    global _MECH_TIMER_START
    if _MECH_TIMER_START is not None:
        entry["elapsedMs"] = int((time.perf_counter() - _MECH_TIMER_START) * 1000)
    append_log(root, entry, state)


def write_blocker_report(root: Path, state: dict[str, Any], cause: str) -> Path:
    from wave_failure import resume_deliver_command

    ec, report_payload = run_wave(root, "report", "blockers")
    report = report_payload.get("report") or {}
    if "resumeCommand" not in report:
        report["resumeCommand"] = resume_deliver_command(root, state)
    out = {
        "verdict": "halt",
        "cause": cause,
        "causeClass": blocker_cause_class(cause),
        "generatedAt": utc_now(),
        "report": report,
        "resumeCommand": report.get("resumeCommand"),
        "remediationAttempts": state.get("remediationAttempts") or {},
    }
    from halt_resume import enrich_legitimate_halt

    enrich_legitimate_halt(
        out,
        root,
        state,
        halt_cause=cause,
        resume_command=str(report.get("resumeCommand") or ""),
    )
    save_state(root, state)
    path = root / BLOCKER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, out)
    return path


def run_plan_validate(
    root: Path,
    args: list[str],
) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_plan_validate.py"), str(root), "validate", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    data: dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {"raw": proc.stdout.strip()}
    data["exitCode"] = proc.returncode
    return proc.returncode, data


def reload_state_from_path(state: dict[str, Any], state_path: Path) -> None:
    if not state_path.is_file():
        return
    try:
        state.update(read_json(state_path))
    except (StateCorruptError, json.JSONDecodeError):
        return


def execute_mechanical(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    step: dict[str, Any],
    *,
    loop_args: list[str] | None = None,
) -> dict[str, Any]:
    global _MECH_TIMER_START
    _MECH_TIMER_START = time.perf_counter()
    try:
        result = _execute_mechanical_inner(root, state, plan, step, loop_args=loop_args)
        elapsed_ms = int((time.perf_counter() - _MECH_TIMER_START) * 1000)
        if isinstance(result, dict):
            result = dict(result)
            result["elapsedMs"] = elapsed_ms
        return result
    finally:
        _MECH_TIMER_START = None


def _execute_mechanical_inner(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    step: dict[str, Any],
    *,
    loop_args: list[str] | None = None,
) -> dict[str, Any]:
    action = step["action"]
    task_list = state.get("source_task_list") or plan.get("source_task_list")
    loop_args = loop_args or []

    if action == "plan":
        if not task_list:
            fail("deliver-loop requires --task-list on first run or state.source_task_list")
        import planning_materialize as pm

        pm.ensure_run_entry_materialized(root, str(task_list))
        plan_args = ["plan", "--task-list", str(task_list)]
        if has_flag(loop_args, "--skip-base-check"):
            plan_args.append("--skip-base-check")
        branch_type = parse_kv(loop_args, "--type")
        if branch_type:
            plan_args.extend(["--type", branch_type])
        ec, data = run_wave(root, *plan_args)
        if ec != 0:
            fail_payload(data, "plan failed", ec)
        plan = load_plan(root)
        persist_cursor(root, state, "state-init")
        return {"executed": "plan", "plan": plan.get("target")}

    if action == "state-init":
        ec, data = run_wave(root, "state", "init", "--plan", str(PLAN_PATH))
        if ec != 0:
            fail_payload(data, "state init failed", ec)
        state.update(load_state(root))
        ensure_driver_fields(state)
        persist_cursor(root, state, "base-capture")
        return {"executed": "state-init"}

    if action == "base-capture":
        ec, data = run_resolve_capture(root)
        if ec != 0:
            fail_payload(data, "base capture failed", ec)
        state.update(load_state(root))
        trunk = (data.get("trunkBase") or {}) if isinstance(data, dict) else {}
        state["baseCapture"] = {
            "name": trunk.get("name"),
            "sha": trunk.get("sha"),
            "source": trunk.get("source"),
            "disclosure": data.get("disclosure"),
            "skipped": bool(data.get("skipped")),
            "at": utc_now(),
        }
        save_state(root, state)
        persist_cursor(root, state, "spec-seed")
        return {"executed": "base-capture", **data}

    if action == "spec-seed":
        tl = step.get("taskList") or task_list
        if not tl:
            fail("spec-seed requires task list")
        ec, data = run_wave(root, "spec-seed", "--task-list", str(tl))
        if ec != 0:
            fail_payload(data, "spec-seed failed", ec)
        state.update(load_state(root))
        state["specSeed"] = {
            "branch": data.get("branch"),
            "commit": data.get("commit"),
            "skipped": bool(data.get("skipped")),
            "at": utc_now(),
        }
        save_state(root, state)
        persist_cursor(root, state, "lock-acquire")
        return {"executed": "spec-seed", **data}

    if action == "lock-acquire":
        target = step.get("target") or (plan.get("target") or {}).get("branch")
        ec, data = run_wave(root, "lock", "acquire", "--target", str(target), "--nonblock")
        if ec not in (0, 20):
            fail_payload(data, "lock acquire failed", ec)
        if ec == 20:
            fail("orchestrator lock held", exit_code=20, holder=data.get("holder"))
        persist_cursor(root, state, "inflight-signal-write")
        return {"executed": "lock-acquire", "target": target}

    if action == "inflight-signal-write":
        target = step.get("target") or (plan.get("target") or {}).get("branch")
        tl = task_list_from(state, plan) or task_list
        write_args = ["run-start", "--target", str(target)]
        if tl:
            write_args.extend(["--task-list", str(tl)])
        ec, data = run_inflight_signal(root, *write_args)
        if ec != 0:
            fail_payload(data, "inflight signal write failed", ec)
        state.update(load_state(root))
        persist_cursor(root, state, "orchestrator-provision")
        return {"executed": "inflight-signal-write", "target": target, **(data or {})}

    if action == "inflight-signal-clear":
        target = step.get("target") or (plan.get("target") or {}).get("branch")
        tl = task_list_from(state, plan) or task_list
        clear_args = ["run-complete", "--target", str(target)]
        if tl:
            clear_args.extend(["--task-list", str(tl)])
        ec, data = run_inflight_signal(root, *clear_args)
        if ec not in (0, 20):
            fail_payload(data, "inflight signal clear failed", ec)
        state.update(load_state(root))
        next_action = step.get("next") or "retrospective"
        persist_cursor(root, state, next_action)
        return {"executed": "inflight-signal-clear", "target": target, **(data or {})}

    if action == "orchestrator-provision":
        ec, data = run_wave(
            root, "orchestrator", "provision", "--plan", str(PLAN_PATH)
        )
        if ec != 0:
            fail_payload(data, "orchestrator provision failed", ec)
        state.update(load_state(root))
        persist_cursor(root, state, "provision-phase")
        return {"executed": "orchestrator-provision"}

    if action == "provision-phase":
        pid = str(step.get("phaseId", ""))
        state["_stallPhaseId"] = pid
        state["_stallWorktreeName"] = phase_worktree_name_for(state, plan, pid)
        ec, data = run_wave(
            root,
            "phase",
            "provision",
            "--phase-id",
            pid,
            "--plan",
            str(PLAN_PATH),
        )
        if ec != 0:
            fail_payload(data, "phase provision failed", ec)
        wt_path = data.get("path") or data.get("worktreePath")
        if not wt_path:
            wt_name = data.get("worktreeName") or data.get("name")
            if wt_name:
                wt_path = str((root / ".sw-worktrees" / wt_name).resolve())
        from planning_progress import provision_deliver_hierarchy

        hier = provision_deliver_hierarchy(root, state)
        if hier.get("verdict") == "fail":
            fail_payload(hier, "hierarchy provision failed", 20)
        worktrees = state.setdefault("phaseWorktrees", {})
        worktrees[pid] = {
            "name": data.get("name") or data.get("worktreeName"),
            "path": wt_path,
        }
        save_state(root, state)
        persist_cursor(root, state, "dispatch-ship", phaseWorktrees=worktrees)
        out: dict[str, Any] = {"executed": "provision-phase", "phaseId": pid, **data}
        if hier.get("notice"):
            out["hierarchyNotice"] = hier["notice"]
        if hier.get("hierarchyMap"):
            out["hierarchyMap"] = hier["hierarchyMap"]
        if hier.get("skipped"):
            out["hierarchySkipped"] = True
        if hier.get("idempotent"):
            out["hierarchyIdempotent"] = True
        return out

    if action == "collect-all-ready":
        head = integration_branch_head(root, state)
        if head:
            state["batchIntegrationHead"] = head
            save_state(root, state)
        enqueued: list[str] = []
        for entry in step.get("phases") or []:
            slug = str(entry.get("phaseSlug", ""))
            ec, data = run_wave(root, "merge", "enqueue", "--phase-slug", slug)
            if ec != 0:
                fail_payload(data, "merge enqueue failed", ec)
            enqueued.append(slug)
        state.update(load_state(root))
        persist_cursor(root, state, "merge-run-next", batchIntegrationHead=state.get("batchIntegrationHead"))
        return {"executed": "collect-all-ready", "enqueued": enqueued, "batchIntegrationHead": state.get("batchIntegrationHead")}

    if action == "phase-teardown-run":
        pid = str(step.get("phaseId", ""))
        ec, data = run_wave(
            root,
            "phase-teardown-run",
            "--phase-id",
            pid,
            "--plan",
            str(PLAN_PATH),
        )
        if ec != 0:
            fail_payload(data, "phase teardown failed", ec)
        state.update(load_state(root))
        persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {"executed": "phase-teardown-run", "phaseId": pid, **data}


    if action == "dispatch-ship":
        return execute_dispatch_ship(root, state, step)

    if action == "dispatch-batch":
        return execute_dispatch_batch(root, state, step)

    if action == "canonical-reemit":
        pid = str(step.get("phaseId", ""))
        slug = str(step.get("phaseSlug") or pid)
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict):
            fail("canonical-reemit missing phase meta", exit_code=2)
        phase_branch = meta.get("branch")
        if not phase_branch:
            fail("canonical-reemit missing phase branch", exit_code=2)
        integration = (state.get("target") or {}).get("branch")
        if not integration:
            fail("canonical-reemit missing integration branch", exit_code=2)
        if meta.get("backgroundDispatchedAt"):
            fail(
                "canonical-reemit refused while background ship in-flight",
                exit_code=20,
                phaseId=pid,
            )
        lease_ec, lease_data = run_wave(
            root,
            "ship-lease",
            "acquire",
            "--integration",
            str(integration),
            "--phase-branch",
            str(phase_branch),
        )
        if lease_ec != 0:
            fail_payload(lease_data, "ship-lease acquire failed", lease_ec)
        try:
            branch_head = phase_branch_head_optional(root, state, slug, str(phase_branch))
            if not branch_head:
                fail("canonical-reemit could not resolve branch head", exit_code=20)
            wt_entry = (state.get("phaseWorktrees") or {}).get(pid, {})
            wt_path = wt_entry.get("path") if isinstance(wt_entry, dict) else None
            smoke_root = Path(str(wt_path)) if wt_path else root
            from ship_pre_pr_smoke import run_pre_pr_smoke

            smoke_ec, smoke_cause = run_pre_pr_smoke(smoke_root)
            if smoke_ec != 0:
                run_dir = root / ".cursor" / "sw-deliver-runs" / slug
                run_dir.mkdir(parents=True, exist_ok=True)
                status_path = run_dir / "status.json"
                doc = build_status_document(
                    verdict="blocked",
                    phase=slug,
                    head=branch_head,
                    cause=smoke_cause or "pre-pr-smoke:failed",
                    ship_chain="incomplete",
                    provenance="canonical-reemit-smoke",
                )
                write_status_atomic(status_path, doc)
                persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
                return {
                    "executed": "canonical-reemit",
                    "phaseId": pid,
                    "phaseSlug": slug,
                    "verdict": "blocked",
                    "cause": smoke_cause,
                    "statusPath": str(status_path),
                }
            pr_number = resolve_pr_number(root, state, slug, None, str(phase_branch))
            verdict, gate, pr_number = derive_terminal_verdict_from_live_evidence(
                root,
                pr_number=pr_number,
                branch_head=branch_head,
            )
            run_dir = root / ".cursor" / "sw-deliver-runs" / slug
            run_dir.mkdir(parents=True, exist_ok=True)
            status_path = run_dir / "status.json"
            reemit_verdict = verdict
            reemit_cause = None
            if verdict == "merge-ready-green":
                reemit_verdict = "blocked"
                reemit_cause = "ship-chain:reverify-required"
            doc = build_status_document(
                verdict=reemit_verdict,
                phase=slug,
                head=branch_head,
                pr=pr_number,
                gate=gate,
                cause=reemit_cause or ((gate or {}).get("reason") if reemit_verdict == "blocked" else None),
                ship_chain="incomplete",
                provenance="live-evidence-recovery",
            )
            write_status_atomic(status_path, doc)
            attempts = state.setdefault("statusReemitAttempts", {})
            attempts[str(pid)] = int(attempts.get(str(pid), 0)) + 1
            meta.pop("backgroundDispatchedAt", None)
            save_state(root, state)
            actor = os.environ.get("SW_RECOVERY_ACTOR") or os.environ.get("USER") or "driver"
            append_log(
                root,
                {
                    "event": "status-canonical-reemit",
                    "phaseId": pid,
                    "phaseSlug": slug,
                    "attempt": attempts[str(pid)],
                    "actor": actor,
                    "verdict": verdict,
                    "head": branch_head,
                },
                state,
            )
            persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
            return {
                "executed": "canonical-reemit",
                "phaseId": pid,
                "phaseSlug": slug,
                "verdict": verdict,
                "statusPath": str(status_path),
            }
        finally:
            run_wave(
                root,
                "ship-lease",
                "release",
                "--integration",
                str(integration),
                "--phase-branch",
                str(phase_branch),
            )

    if action == "collect-status":
        slug = str(step.get("phaseSlug", ""))
        pid = str(step.get("phaseId") or "")
        meta = (state.get("phases") or {}).get(pid, {})
        ec, data = run_wave(root, "status", "collect", "--phase-slug", slug)
        if ec != 0:
            fail_payload(data, "status collect failed", ec)
        if not pid:
            for candidate, candidate_meta in (state.get("phases") or {}).items():
                if isinstance(candidate_meta, dict) and candidate_meta.get("slug") == slug:
                    pid = str(candidate)
                    meta = candidate_meta
                    break
        if isinstance(meta, dict):
            release_inline_dispatch_lease(root, state, meta)
        state.update(load_state(root))
        persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {"executed": "collect-status", "phaseSlug": slug, **data}

    if action == "post-merge-verify-remediate":
        slug = str(step.get("phaseSlug", ""))
        pid = str(step.get("phaseId", ""))
        ec, data = run_wave(root, "verify", "run-after-merge", "--phase-slug", slug)
        refresh_merge_queue_liveness_cas(root, state)
        if ec == 0:
            state.update(load_state(root))
            meta = (state.get("phases") or {}).get(pid)
            if isinstance(meta, dict):
                meta.pop("postMergeVerifyPending", None)
                meta.pop("verifyEnvironmental", None)
                meta.pop("cause", None)
                meta["status"] = "green-merged"
                meta["updatedAt"] = utc_now()
                save_state(root, state)
            persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
            return {"executed": "post-merge-verify-remediate", "phaseSlug": slug, **data}
        if ec == 10 and data.get("cause") == "verify:environmental":
            state.update(load_state(root))
            attempts = state.setdefault("verifyRemediationAttempts", {})
            attempts[pid] = int(step.get("attempt") or attempts.get(pid, 0))
            meta = (state.get("phases") or {}).get(pid)
            if isinstance(meta, dict):
                _record_remediation_cause(meta, "verify:environmental")
                meta["lastRemediationAt"] = utc_now()
                meta["postMergeVerifyPending"] = True
                save_state(root, state)
            next_action = (
                "merge-run-next"
                if merge_queue_drain_preferred(state)
                else "post-merge-verify-remediate"
            )
            persist_cursor(root, state, next_action)
            return {
                "executed": "post-merge-verify-remediate",
                "phaseSlug": slug,
                "causeClass": "environmental",
                "nextAction": next_action,
                **data,
            }
        if ec == 20 and data.get("cause") == "verify:failed":
            state.update(load_state(root))
            meta = (state.get("phases") or {}).get(pid)
            if isinstance(meta, dict):
                _record_remediation_cause(meta, "verify:failed")
                meta["lastRemediationAt"] = utc_now()
                save_state(root, state)
            persist_cursor(root, state, "remediate")
            return {
                "executed": "post-merge-verify-remediate",
                "verifyFailed": True,
                "causeClass": "regression",
                **data,
            }
        fail_payload(data, "post-merge verify remediation failed", ec)

    if action == "merge-enqueue":
        slug = str(step.get("phaseSlug", ""))
        ec, data = run_wave(root, "merge", "enqueue", "--phase-slug", slug)
        if ec != 0:
            fail_payload(data, "merge enqueue failed", ec)
        persist_cursor(root, state, "merge-run-next")
        return {"executed": "merge-enqueue", "phaseSlug": slug}

    if action == "merge-run-next":
        fixture_tree_clean_or_halt(root, state)
        batch_halt = batch_integration_head_halt(root, state)
        if batch_halt:
            fail(
                batch_halt.get("cause") or "batch-integration-head-moved",
                exit_code=20,
                halt="blocked",
                **{k: v for k, v in batch_halt.items() if k not in ("action", "resume")},
            )
        ec, data = run_wave(root, "merge", "run-next")
        if ec == 10 and data.get("cause") == "verify:environmental":
            # Reload disk state first — merge-run-next already dequeued + recorded
            # completedMerges; saving the pre-call in-memory snapshot would wipe that (R9).
            state.update(load_state(root))
            refresh_merge_queue_liveness_cas(root, state)
            slug = str(data.get("phase") or "")
            for pid, meta in (state.get("phases") or {}).items():
                if isinstance(meta, dict) and meta.get("slug") == slug:
                    attempts = state.setdefault("verifyRemediationAttempts", {})
                    attempts[str(pid)] = int(attempts.get(str(pid), 0)) + 1
                    _record_remediation_cause(meta, "verify:environmental")
                    meta["lastRemediationAt"] = utc_now()
                    meta["postMergeVerifyPending"] = True
                    save_state(root, state)
                    break
            next_action = (
                "merge-run-next"
                if merge_queue_drain_preferred(state)
                else "post-merge-verify-remediate"
            )
            persist_cursor(root, state, next_action)
            return {
                "executed": "merge-run-next",
                "verifyEnvironmental": True,
                "causeClass": "environmental",
                "nextAction": next_action,
                **data,
            }
        if ec == 20 and data.get("cause") == "verify:failed":
            slug = str(data.get("phase") or "")
            state.update(load_state(root))
            for pid, meta in (state.get("phases") or {}).items():
                if isinstance(meta, dict) and meta.get("slug") == slug:
                    _record_remediation_cause(meta, "verify:failed")
                    meta["lastRemediationAt"] = utc_now()
                    save_state(root, state)
                    break
            persist_cursor(root, state, "remediate")
            return {
                "executed": "merge-run-next",
                "verifyFailed": True,
                "causeClass": "regression",
                "recommendedCommand": "/sw-stabilize",
                **data,
            }
        if ec == 20 and data.get("cause") == "merge-run-next:timeout":
            from wave_failure import resume_deliver_command

            state.update(load_state(root))
            preserve_merge_queue_on_halt(state)
            state["verdict"] = "blocked"
            state["cause"] = "merge-run-next:timeout"
            save_state(root, state)
            path = write_blocker_report(root, state, "merge-run-next:timeout")
            persist_cursor(
                root,
                state,
                "halt-blocked",
                blockerReport=str(path),
                budgetHalt=False,
            )
            fail_payload(
                data,
                "merge run-next timed out",
                ec,
                halt="blocked",
                resumeCommand=data.get("resumeCommand") or resume_deliver_command(root, state),
                blockerReport=str(path),
            )
        if ec not in (0, 10):
            fail_payload(data, "merge run-next failed", ec)
        state.update(load_state(root))
        refresh_batch_integration_head(root, state)
        persist_cursor(root, state, "provision-phase")
        state.update(load_state(root))
        clear_batch_integration_head_if_idle(state)
        save_state(root, state)
        return {"executed": "merge-run-next", **data}

    if action == "advance-wave":
        wave_num = int(state.get("currentWave") or 1) + 1
        persist_cursor(root, state, "provision-phase", currentWave=wave_num)
        return {"executed": "advance-wave", "currentWave": wave_num}

    if action == "all-phases-complete":
        sync_terminal_state(root, state)
        persist_cursor(root, state, "inflight-signal-clear")
        return {"executed": "all-phases-complete", "next": "inflight-signal-clear"}

    if action == "finalize-completion":
        ec, data = run_wave(root, "completion", "finalize-if-merged")
        if ec != 0:
            fail_payload(
                data,
                "finalize completion failed",
                ec,
                remediation=(
                    "post-merge playbook: single-unit set-index-status + append-log-idempotent on a docs branch; "
                    "never bare reconcile.py reconcile on main; retry via bash scripts/wave.py completion finalize-if-merged"
                ),
            )
        state.update(load_state(root))
        orch = orchestrator_worktree_path(root, state)
        # R1: reconcile owns the living-doc lock via living_doc_write_lock — do not
        # outer-acquire here (nested acquire deadlocks against the reconcile subprocess).
        target = (state.get("target") or {}).get("branch")
        living_args = ["living-docs", "reconcile", "--commit"]
        if orch is not None:
            living_args.extend(["--orchestrator-worktree", str(orch)])
        living_ec, living_data = run_wave(root, *living_args)
        if living_ec != 0:
            fail_payload(
                living_data,
                "living-docs reconcile failed during finalize-completion",
                living_ec,
                remediation=(
                    "ensure orchestrator worktree is on a non-default branch; "
                    "retry via /sw-deliver run after fixing INDEX currency"
                ),
            )
        from publish_surface_audit import emit_publish_surface_audit

        publish_audit = emit_publish_surface_audit(root, write=True)
        if publish_audit.get("verdict") == "not-ready":
            fail_payload(
                publish_audit,
                "publish-surface audit not ready",
                20,
                remediation=str(publish_audit.get("resumeCommand") or ""),
            )
        from host_lib import load_workflow_config
        from planning_store import close_delivery_units
        import planning_index_issue as pii
        from wave_living_docs import prd_number_from_state

        cfg = load_workflow_config(root)
        prd = prd_number_from_state(state, plan)
        slug = str((state.get("target") or {}).get("slug") or plan.get("slug") or "")
        prd_unit_id = pii.resolve_prd_unit_id(root, prd, slug=slug or None) if prd else None
        closure: dict[str, Any] | None = None
        if prd_unit_id:
            from planning_store import audit_closure_completeness, doctor_absorb_pollution

            doctor = doctor_absorb_pollution(root, cfg, prd_unit_id=prd_unit_id)
            if doctor.get("verdict") == "fail":
                fail_payload(
                    doctor,
                    "absorb pollution doctor failed",
                    20,
                    remediation=str(doctor.get("resumeCommand") or "python3 scripts/planning_store.py doctor"),
                )
            closure = close_delivery_units(root, cfg, prd_unit_id, state=state)
            audit = closure.get("closureAudit") or audit_closure_completeness(
                root, cfg, prd_unit_id, closure_result=closure, state=state
            )
            if audit.get("verdict") == "not-ready":
                fail_payload(
                    audit,
                    "closure audit not ready",
                    20,
                    remediation=str(audit.get("resumeCommand") or ""),
                )
            if closure.get("verdict") == "not-ready":
                fail_payload(
                    closure,
                    "close-delivery-units not ready",
                    20,
                    remediation=str(closure.get("resumeCommand") or ""),
                )
        target = (state.get("target") or {}).get("branch")
        task_list = task_list_from(state, plan)
        clear_args = ["run-complete"]
        if target:
            clear_args.extend(["--target", str(target)])
        if task_list:
            clear_args.extend(["--task-list", str(task_list)])
        clear_ec, clear_data = run_inflight_signal(root, *clear_args)
        if clear_ec != 0:
            fail_payload(clear_data, "inflight clear failed", clear_ec)
        state.update(load_state(root))
        cleanup_payload: dict[str, Any] | None = None
        try:
            from cleanup_lib import apply_autonomous_cleanup, cleanup_autonomy_mode

            if cleanup_autonomy_mode(root) == "auto":
                cleanup_payload = apply_autonomous_cleanup(root)
        except Exception as exc:
            cleanup_payload = {"verdict": "halt", "error": str(exc)}
        persist_cursor(root, state, "suggest-cleanup")
        result: dict[str, Any] = {
            "executed": "finalize-completion",
            "cleanupSuggestion": data.get("cleanupSuggestion"),
            "publishSurfaceAudit": publish_audit,
            **data,
        }
        if closure is not None:
            result["closure"] = closure
        if cleanup_payload is not None:
            result["autonomousCleanup"] = cleanup_payload
        return result

    if action == "suggest-cleanup":
        suggestion = str(step.get("cleanupSuggestion") or "Run `/sw-cleanup` to prune merged branches and stale worktrees.")
        persist_cursor(root, state, "terminal")
        return {"executed": "suggest-cleanup", "cleanupSuggestion": suggestion}


    if action == "wave-plan-persist":
        policy = read_config_plan_policy(root)
        proposal = {"waves": plan.get("waves") or []}
        frozen = {"waves": plan.get("waves") or [], "edges": plan.get("edges") or []}
        state_path = resolve_state_path(root, state_hint=state)
        if policy == "proposed":
            _, result = run_plan_validate(
                root,
                [
                    "--tier",
                    "wave",
                    "--proposal",
                    json.dumps(proposal),
                    "--frozen-plan",
                    json.dumps(frozen),
                    "--record-rejection",
                    "--phase-id",
                    "wave",
                    "--state-path",
                    str(state_path),
                ],
            )
            reload_state_from_path(state, state_path)
            if result.get("verdict") != "pass":
                wave_plan = result.get("fallback") or wave_fallback_canonical_waves(
                    frozen, root, recorded_parent=state.get("waveBatchingPlan")
                )
            else:
                wave_plan = result.get("plan") or wave_fallback_canonical_waves(
                    frozen, root, recorded_parent=state.get("waveBatchingPlan")
                )
        else:
            result = validate_wave_plan(root, proposal, frozen_plan=frozen)
            if result.get("verdict") != "pass":
                wave_plan = result.get("fallback") or wave_fallback_canonical_waves(frozen, root)
            else:
                wave_plan = result.get("plan") or wave_fallback_canonical_waves(frozen, root)
        persist_wave_batching_plan(state, wave_plan, fail)
        set_wave_lifecycle(state, LIFECYCLE_WAVE_VALIDATED)
        save_state(root, state)
        surface_wave_plan_chosen(root, wave_plan)
        persist_cursor(root, state, "provision-phase")
        return {"executed": "wave-plan-persist", "lifecycle": get_lifecycle(state)}

    if action == "phase-plan-entry":
        pid = str(step.get("phaseId", ""))
        slug = str(step.get("phaseSlug") or pid)
        set_phase_lifecycle(state, pid, LIFECYCLE_PHASE_PLAN_PENDING)
        policy = read_config_plan_policy(root)
        proposal = mechanical_phase_plan(root, pid, slug, state)
        if policy == "proposed":
            state_path = resolve_state_path(root, state_hint=state)
            validate_proposal = {
                "steps": proposal.get("steps") or [],
                "phaseId": pid,
            }
            _, result = run_plan_validate(
                root,
                [
                    "--tier",
                    "phase",
                    "--phase-type",
                    "ship",
                    "--proposal",
                    json.dumps(validate_proposal),
                    "--phase-id",
                    pid,
                    "--record-rejection",
                    "--state-path",
                    str(state_path),
                ],
            )
            reload_state_from_path(state, state_path)
            if result.get("verdict") != "pass":
                phase_plan = result.get("fallback") or phase_fallback_canonical_chain(
                    root,
                    "ship",
                    pid,
                    recorded_parent=state.get("waveBatchingPlan"),
                )
            else:
                phase_plan = result.get("plan") or proposal
        else:
            phase_plan = proposal
        run_dir = phase_run_dir_for_slug(root, slug)
        run_dir.mkdir(parents=True, exist_ok=True)
        from plan_persist import persist_phase_plan, phase_plan_path

        persist_phase_plan(phase_plan_path(run_dir), phase_plan)
        set_phase_lifecycle(state, pid, LIFECYCLE_PHASE_PLAN_VALIDATED)
        save_state(root, state)
        surface_phase_plan_chosen(
            root,
            phase_id=pid,
            phase_slug=slug,
            phase_plan=phase_plan,
        )
        if task_list_from(state, plan):
            from execute_ship import supervised_plan_halt_required, resolve_run_dir
            run_dir = phase_run_dir_for_slug(root, slug)
            if supervised_plan_halt_required(root, run_dir):
                persist_cursor(root, state, "dispatch-ship")
                return {
                    "executed": "phase-plan-entry",
                    "phaseId": pid,
                    "phaseSlug": slug,
                    "planPath": str(phase_plan_path(run_dir)),
                    "lifecycle": get_lifecycle(state),
                    "supervisedHalt": True,
                    "halt": "execute:supervised-plan-confirm",
                }
                persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {
            "executed": "phase-plan-entry",
            "phaseId": pid,
            "phaseSlug": slug,
            "planPath": str(phase_plan_path(run_dir)),
            "lifecycle": get_lifecycle(state),
        }

    if action == "halt-blocked":
        cause = str(step.get("cause", "blocked"))
        if step.get("budgetHalt") or is_budget_halt(cause):
            return clean_consolidated_halt(root, state, plan, cause)
        if cause.startswith("phase-timeout:"):
            pid = cause.split(":", 1)[1]
            phases = state.setdefault("phases", {})
            meta = phases.get(pid)
            if isinstance(meta, dict) and meta.get("status") == "in-flight":
                meta["status"] = "blocked"
                meta["cause"] = cause
                meta["updatedAt"] = utc_now()
        state["verdict"] = "blocked"
        state["cause"] = cause
        path = write_blocker_report(root, state, cause)
        persist_cursor(root, state, "halt-blocked", blockerReport=str(path))
        return {"executed": "halt-blocked", "cause": cause, "blockerReport": str(path)}

    fail(f"unknown mechanical action: {action}")


def _mechanical_elapsed_ms() -> int:
    global _MECH_TIMER_START
    if _MECH_TIMER_START is None:
        return 0
    return int((time.perf_counter() - _MECH_TIMER_START) * 1000)


def cmd_watchdog_check(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    cause = check_watchdog(root, state)
    timeout_min = phase_timeout_minutes(root)
    in_flight: list[dict[str, Any]] = []
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", pid)
        status_path = status_file_for(root, slug, None, state)
        in_flight.append(
            {
                "phaseId": pid,
                "phaseSlug": slug,
                "startedAt": meta.get("startedAt"),
                "hasStatusJson": status_path.is_file(),
            }
        )
    if cause:
        emit(
            {
                "verdict": "fail",
                "action": "watchdog-check",
                "cause": cause,
                "phaseTimeoutMinutes": timeout_min,
                "inFlight": in_flight,
                "recommendedCommand": "bash scripts/wave.py deliver-loop",
            },
            exit_code=20,
        )
    emit(
        {
            "verdict": "pass",
            "action": "watchdog-check",
            "phaseTimeoutMinutes": timeout_min,
            "inFlight": in_flight,
        }
    )


def cmd_deliver_loop(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    max_steps = int(parse_kv(args, "--max-steps", "12") or "12")
    from wave_deliver import resolve_task_list_arg

    task_list = resolve_task_list_arg(root, args) or parse_kv(args, "--task-list")

    state = load_state(root, task_list)
    plan = load_plan(root)
    resumed = bool(state.get("verdict") == "running" and state.get("phases"))
    if task_list and resumed:
        entry = apply_resume_entry(root, state, plan, args)
        if entry.get("orchestratorAdopt", {}).get("adopted"):
            state = load_state(root, task_list)
            plan = load_plan(root)
            resumed = bool(state.get("verdict") == "running" and state.get("phases"))

    assert_run_identity(root, state, task_list, args)
    assert_driver_adopt_gate(state, args)

    if task_list and not state.get("source_task_list"):
        state["source_task_list"] = task_list

    if not plan and task_list:
        state.setdefault("verdict", "running")
        ensure_driver_fields(state)
        save_state(root, state)

    steps_taken: list[dict[str, Any]] = []
    for _ in range(max_steps):
        state = load_state(root, task_list)
        plan = load_plan(root)
        if task_list:
            state["source_task_list"] = task_list
        init_budget_counters(state)
        step = compute_next_action(root, state, plan)
        if step.get("phaseId"):
            pid = str(step["phaseId"])
            state["_stallPhaseId"] = pid
            state["_stallWorktreeName"] = phase_worktree_name_for(state, plan, pid)
        if step["action"] != "halt-blocked":
            record_budget_tick(root, state, step["action"])
            save_state(root, state)
            budget_cause = check_budget_halt(root, state)
            if budget_cause:
                step = {
                    "action": "halt-blocked",
                    "cause": budget_cause,
                    "budgetHalt": True,
                    "resume": True,
                }
        step["resumed"] = resumed

        if dry_run:
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "dry_run": True,
                    "resumed": resumed,
                    "next": step,
                }
            )

        if step["action"] in AGENT_ACTIONS | TERMINAL_ACTIONS:
            if step["action"] == "terminal":
                emit(
                    {
                        "verdict": "pass",
                        "action": "deliver-loop",
                        "resumed": resumed,
                        "terminal": True,
                        "runVerdict": step.get("verdict"),
                        "nextAction": state.get("nextAction"),
                    }
                )
            if step["action"] == "remediate":
                pid = str(step.get("phaseId", ""))
                cause_class = str(step.get("causeClass") or "regression")
                attempts_key = (
                    "verifyRemediationAttempts"
                    if cause_class == "environmental"
                    else "remediationAttempts"
                )
                attempts = state.setdefault(attempts_key, {})
                attempts[pid] = int(step.get("attempt", 1))
                meta = (state.get("phases") or {}).get(pid)
                if isinstance(meta, dict):
                    meta["lastRemediationAt"] = utc_now()
                save_state(root, state)
                refresh_batch_integration_head(root, state)
                persist_cursor(root, state, "remediate")
            elif step["action"] == "dispatch-batch":
                phase_ids = [str(p) for p in step.get("phaseIds") or []]
                mark_phases_in_flight(state, phase_ids, background=True)
                persist_cursor(
                    root,
                    state,
                                batchPhaseIds=phase_ids,
                )
            elif step["action"] == "dispatch-ship":
                pid = str(step.get("phaseId", ""))
                meta = (state.get("phases") or {}).get(pid)
                if isinstance(meta, dict):
                    lease_ec, lease_data = acquire_inline_dispatch_lease(
                        root, state, pid, meta
                    )
                    if lease_ec != 0:
                        fail_payload(
                            lease_data,
                            "dispatch-ship lease acquire failed",
                            lease_ec,
                        )
                mark_phases_in_flight(state, [pid], background=False)
                persist_cursor(root, state, "dispatch-ship")
            elif step["action"] == "halt-blocked":
                execute_mechanical(root, state, plan, step, loop_args=args)
                emit(
                    {
                        "verdict": "blocked",
                        "action": "deliver-loop",
                        "resumed": resumed,
                        "halt": True,
                        "cause": step.get("cause"),
                        "blockerReport": str(root / BLOCKER_PATH),
                        "nextAction": "halt-blocked",
                    },
                    20,
                )
            else:
                if step["action"] in ("retrospective", "terminal-ship"):
                    sync_terminal_state(root, state)
                    save_state(root, state)
                persist_cursor(root, state, step["action"])
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitAgent": step["action"] in AGENT_ACTIONS,
                    "next": step,
                    "stepsTaken": steps_taken,
                }
            )

        if step["action"] in AWAIT_ACTIONS:
            persist_cursor(root, state, step["action"])
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitInFlight": True,
                    "awaitAgent": False,
                    "next": step,
                    "stepsTaken": steps_taken,
                }
            )

        if step["action"] not in MECHANICAL_ACTIONS:
            fail(f"unhandled action: {step['action']}", step=step)

        result = execute_mechanical(root, state, plan, step, loop_args=args)
        steps_taken.append(result)
        resumed = True
        if step["action"] == "dispatch-ship" and result.get("awaitAgent"):
            ship_next = {
                "action": "dispatch-ship",
                "phaseId": result.get("phaseId") or step.get("phaseId"),
                "phaseSlug": result.get("phaseSlug") or step.get("phaseSlug"),
                "resume": True,
                "note": "ship-loop awaitAgent — run agent step in phase worktree",
                "shipStep": result.get("shipStep"),
                "shipContract": result.get("shipContract"),
            }
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitAgent": True,
                    "next": ship_next,
                    "stepsTaken": steps_taken,
                }
            )
        if step["action"] == "dispatch-batch" and result.get("awaitAgent"):
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitAgent": True,
                    "next": {
                        "action": "dispatch-batch",
                        "phaseIds": result.get("phaseIds") or step.get("phaseIds"),
                        "resume": True,
                    },
                    "stepsTaken": steps_taken,
                }
            )
        append_log(
            root,
            {
                "event": "execute-mechanical",
                "action": step["action"],
                "executed": result.get("executed"),
                "elapsedMs": result.get("elapsedMs"),
            },
            load_state(root, task_list),
        )
        if not drain_mechanical_enabled(root):
            next_after = compute_next_action(root, load_state(root, task_list), load_plan(root))
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitAgent": False,
                    "drainMechanical": False,
                    "next": next_after,
                    "stepsTaken": steps_taken,
                }
            )

    next_after = compute_next_action(root, load_state(root, task_list), load_plan(root))
    if (
        drain_mechanical_enabled(root)
        and next_after.get("action") in MECHANICAL_ACTIONS
    ):
        emit(
            {
                "verdict": "blocked",
                "action": "deliver-loop",
                "resumed": resumed,
                "halt": True,
                "cause": DRAIN_STEP_BUDGET_HALT,
                "note": f"step budget ({max_steps}) reached while next action is still mechanical",
                "stepsTaken": steps_taken,
                "next": next_after,
            },
            20,
        )
    emit(
        {
            "verdict": "pass",
            "action": "deliver-loop",
            "resumed": resumed,
            "note": f"step budget ({max_steps}) reached",
            "stepsTaken": steps_taken,
            "next": next_after,
        }
    )


def cmd_remediation_default(root: Path, _args: list[str]) -> None:
    emit(
        {
            "verdict": "pass",
            "maxAttempts": remediation_max(root),
            "default": DEFAULT_REMEDIATION_MAX,
        }
    )


def cmd_budget_tick(root: Path, args: list[str]) -> None:
    state = load_state(root)
    plan = load_plan(root)
    next_action = parse_kv(args, "--next-action")
    if not next_action:
        next_action = compute_next_action(root, state, plan)["action"]
    record_budget_tick(root, state, next_action)
    save_state(root, state)
    emit(
        {
            "verdict": "pass",
            "action": "budget-tick",
            "nextAction": next_action,
            "driverIterationCount": state.get("driverIterationCount"),
            "noProgressStreak": state.get("noProgressStreak"),
            "budgetCounters": state.get("budgetCounters"),
        }
    )


def cmd_budget_check(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    cause = check_budget_halt(root, state)
    emit(
        {
            "verdict": "blocked" if cause else "pass",
            "action": "budget-check",
            "budgetHalt": cause,
            "driverIterationCount": state.get("driverIterationCount"),
            "noProgressStreak": state.get("noProgressStreak"),
            "budgetCounters": state.get("budgetCounters"),
            "runStartedAt": state.get("runStartedAt"),
        },
        exit_code=20 if cause else 0,
    )


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: wave_deliver_loop.py <root> deliver-loop [--task-list PATH] [--dry-run]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else "deliver-loop"
    args = sys.argv[3:]

    if cmd == "deliver-loop":
        cmd_deliver_loop(root, args)
    elif cmd == "remediation-default":
        cmd_remediation_default(root, args)
    elif cmd == "budget-tick":
        cmd_budget_tick(root, args)
    elif cmd == "budget-check":
        cmd_budget_check(root, args)
    elif cmd == "compute-next":
        state = load_state(root)
        plan = load_plan(root)
        emit(
            {
                "verdict": "pass",
                "next": compute_next_action(root, state, plan),
            }
        )
    elif cmd == "watchdog":
        if not args or args[0] != "check":
            fail("watchdog subcommand required: check")
        cmd_watchdog_check(root, args[1:])
    elif cmd == "living-doc-reconcile":
        cmd_manual_living_doc_reconcile(root, args)
    elif cmd == "living-doc-reconcile-suggestion":
        state = load_state(root)
        emit({"verdict": "pass", "action": "living-doc-reconcile-suggestion", **manual_living_doc_reconcile_suggestion(root, state)})
    else:
        fail(f"unknown command: {cmd}")



def poll_phase_ship_gate(root: Path, pr: str | None = None) -> dict[str, Any]:
    """Phase-mode CI poll via check-gate backoff — never blocking blocking host watch (R12)."""
    from watch_ci_lib import poll_check_gate_settled

    return poll_check_gate_settled(root, pr)


if __name__ == "__main__":
    main()
