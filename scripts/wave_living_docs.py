#!/usr/bin/env python3
"""Living-doc reconciliation for /sw-deliver (R47–R51): INDEX, COMPLETION-LOG, GAP-BACKLOG."""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_issue as pii
import planning_paths
from planning_artifact_handle import issue_store_is_effective
VALID_INDEX_STATUSES = frozenset({"not-started", "in-progress", "complete"})
TERMINAL_PHASE_STATUSES = frozenset({"green-merged", "teardown-pending", "teardown-complete"})
GAP_CLOSEOUT_RETRY_MAX_ATTEMPTS = 3
GAP_CLOSEOUT_RETRY_BASE_SECONDS = 0.2
GAP_CLOSEOUT_RETRY_CAP_SECONDS = 30.0

def living_paths(root: Path) -> tuple[str, ...]:
    return planning_paths.living_paths_rel(planning_paths.load_planning_dirs(root))


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


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def load_state(root: Path) -> dict[str, Any]:
    from wave_state import resolve_state_path

    path = resolve_state_path(root)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def load_plan(root: Path, state: dict[str, Any] | None = None) -> dict[str, Any]:
    if state is None:
        state = load_state(root)
    if not state.get("planHash"):
        return {}
    import wave_run_plan as run_plan

    return run_plan.load_plan_for_state(root, state)


def prd_number_from_state(state: dict[str, Any], plan: dict[str, Any]) -> str | None:
    raw = state.get("prd_number") or plan.get("prd_number")
    if raw is None:
        return None
    return str(raw).zfill(3)


def derive_index_status(state: dict[str, Any], merged_to_main: bool) -> str:
    phases = state.get("phases") or {}
    if not phases:
        return "not-started"
    statuses = [str((meta or {}).get("status") or "pending") for meta in phases.values()]
    if merged_to_main:
        return "complete"
    if all(s in TERMINAL_PHASE_STATUSES for s in statuses):
        completion = state.get("completion") or {}
        if completion.get("status") == "completed-pending-merge":
            return "complete"
    if any(s not in ("pending",) for s in statuses):
        return "in-progress"
    return "not-started"


def target_merge_detected(root: Path, state: dict[str, Any]) -> bool:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_compound.py"), str(root), "completion", "check-merge"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        return False
    try:
        data = json.loads(proc.stdout)
        return bool(data.get("merged"))
    except json.JSONDecodeError:
        return False


def resolve_worktree(root: Path, args: list[str]) -> Path:
    wt = parse_kv(args, "--worktree")
    if wt:
        return Path(wt).resolve()
    orch = parse_kv(args, "--orchestrator-worktree")
    if orch:
        return Path(orch).resolve()
    return root.resolve()


def run_reconcile_script(root: Path, *cmd: str) -> dict[str, Any]:
    script = SCRIPT_DIR / "reconcile.py"
    from _sw import interpreter
    probe = interpreter.probe()
    proc = subprocess.run(
        [*probe.executable, str(script), *cmd],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    out = proc.stdout.strip()
    try:
        data = json.loads(out) if out.startswith("{") else {"raw": out}
    except json.JSONDecodeError:
        data = {"raw": out, "stderr": proc.stderr.strip()}
    if proc.returncode != 0:
        fail(
            data.get("error") or proc.stderr.strip() or "reconcile failed",
            exit_code=proc.returncode,
            **{k: v for k, v in data.items() if k != "error"},
        )
    return data


def _enforce_deliver_cwd_guard(*, allow_default_branch: bool = False) -> None:
    import deliver_cwd_guard

    deliver_cwd_guard.enforce(allow_default_branch=allow_default_branch)


def _enforce_default_branch_commit_guard(
    root: Path,
    worktree: Path,
    *,
    allow_default_branch: bool = False,
) -> None:
    import default_branch_commit_guard

    default_branch_commit_guard.enforce(
        root,
        worktree=worktree,
        allow_default=allow_default_branch,
    )


def git_commit_living_docs(worktree: Path, prd: str, dry_run: bool, repo_root: Path | None = None) -> str | None:
    if living_doc_write_banned(worktree):
        return None
    top = worktree
    proc = subprocess.run(
        ["git", "-C", str(top), "status", "--porcelain", "--", *living_paths(top)],
        text=True,
        capture_output=True,
    )
    if not proc.stdout.strip():
        return None
    if dry_run:
        return "dry-run"
    repo = (repo_root or top).resolve()
    _enforce_default_branch_commit_guard(repo, top)
    _enforce_deliver_cwd_guard()
    subprocess.run(["git", "-C", str(top), "add", *living_paths(top)], check=True)
    msg = f"chore: living-doc reconcile for PRD {prd}"
    proc = subprocess.run(
        ["git", "-C", str(top), "commit", "-m", msg],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "living-doc commit failed")
    sha_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return sha_proc.stdout.strip()


def live_phase_status_rows(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Per-phase live view for mid-run /sw-status (PRD 013 R15)."""
    phases = state.get("phases") or {}
    remediation = state.get("remediationAttempts") or {}
    rows: list[dict[str, Any]] = []
    for pid in sorted(phases.keys(), key=lambda x: int(x) if str(x).isdigit() else str(x)):
        meta = phases[pid] if isinstance(phases[pid], dict) else {}
        slug = str(meta.get("slug") or "")
        rows.append(
            {
                "phaseId": pid,
                "slug": slug,
                "status": meta.get("status", "pending"),
                "attempt": remediation.get(slug, remediation.get(str(slug), 0)),
                "blocker": meta.get("cause"),
            }
        )
    return rows


def cmd_phase_status_live(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if target:
        from wave_state import load_deliver_state

        state = load_deliver_state(root, target=target)
    else:
        state = load_state(root)
    rows = live_phase_status_rows(state)
    emit(
        {
            "verdict": "pass",
            "action": "phase-status-live",
            "target": (state.get("target") or {}).get("branch"),
            "verdictRun": state.get("verdict"),
            "livePhaseStatus": rows,
        }
    )




def project_legacy_compat(root: Path, *, dry_run: bool = False) -> dict[str, Any] | None:
    """Emit legacy GAP-BACKLOG/INDEX projections when planningDir is flipped (R27)."""
    import planning_legacy_projection as plp

    return plp.project_all(root, dry_run=dry_run)


def cmd_regenerate_index(root: Path, args: list[str]) -> None:
    """Regenerate planning INDEX structural region under living-doc lock (PRD 031 R24)."""
    from wave_living_doc_lock import living_doc_write_lock
    import planning_index_gen as pig

    state = load_state(root)
    target = (state.get("target") or {}).get("branch")
    dry_run = has_flag(args, "--dry-run")
    with living_doc_write_lock(root, target=target, holder="planning-index-generator"):
        content = pig.generate_index(root, writer="generator")
        rel = pig.index_rel(root)
        legacy = None
        if not dry_run:
            pig.write_index(root, content)
            legacy = project_legacy_compat(root, dry_run=False)
        emit(
            {
                "verdict": "pass",
                "action": "planning-index-regenerate",
                "path": rel,
                "unitCount": len(pig.discover_units(root)),
                "dryRun": dry_run,
                "legacyProjection": legacy,
            }
        )


def living_doc_write_banned(root: Path) -> bool:
    """PRD 061 R3: ban tracked living-doc writes when issue-store is effective."""
    return issue_store_is_effective(root)


def _completion_events_cache_path(root: Path) -> Path:
    return root / ".cursor" / "hooks" / "state" / "planning-completion-events.json"


def append_completion_store_event(
    root: Path,
    *,
    prd_id: str,
    unit_id: str,
    status: str,
    evidence: dict[str, object] | None = None,
) -> dict[str, object]:
    """PRD 061 R5: append completion as a store event (not COMPLETION-LOG file)."""
    from host_lib import load_workflow_config
    from planning_store import get_backend

    event = {
        "prd_id": prd_id,
        "unit_id": unit_id,
        "status": status,
        "evidence": evidence or {},
    }
    cache = _completion_events_cache_path(root)
    cache.parent.mkdir(parents=True, exist_ok=True)
    events: list[dict] = []
    if cache.is_file():
        events = json.loads(cache.read_text(encoding="utf-8"))
    events.append(event)
    cache.write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")

    worktree = planning_paths.git_root(root)
    cfg = load_workflow_config(worktree)
    backend = get_backend(worktree, cfg)
    # Synthetic operational ledger — not a private PRD body. Pin public visibility so
    # public issue-store hosts (probe-inconclusive / public) accept the put; local
    # cache above remains the authoritative read path for terminal prepare.
    body = (
        "---\n"
        "visibility: public\n"
        "artifactType: completion-log\n"
        "---\n"
        + json.dumps({"events": events}, indent=2)
        + "\n"
    )
    backend.put(
        "planning-completion-log",
        ".cursor/hooks/state/planning-completion-events.json",
        body,
    )
    return {"verdict": "stored", "action": "completion-store-event", "event_count": len(events)}


def read_completion_evidence(root: Path, prd_id: str) -> dict[str, object] | None:
    """PRD 061 R4/R5: read completion evidence from store cache under issue-store."""
    from sw_scripts_resolve import is_shipwright_self_repo

    if not living_doc_write_banned(root) and is_shipwright_self_repo(root):
        return None
    cache = _completion_events_cache_path(root)
    if not cache.is_file():
        return None
    try:
        events = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(events, list):
        return None
    prd = prd_id.zfill(3)
    for ev in reversed(events):
        if str(ev.get("prd_id", "")).zfill(3) == prd:
            return ev
    return None


def read_index_status_evidence(root: Path, prd_id: str, *, slug: str | None = None) -> dict[str, object] | None:
    """PRD 061 R4 / PRD 325 R12: read index status from store projection cache."""
    from sw_scripts_resolve import is_shipwright_self_repo

    if not living_doc_write_banned(root) and is_shipwright_self_repo(root):
        return None
    return pii.read_projected_index_status(root, prd_id, slug=slug)


def facade_set_index_status(
    root: Path,
    prd: str,
    status: str,
    *,
    slug: str | None = None,
    dry_run: bool = False,
) -> dict[str, object]:
    """Route index status writes through planning store facade under issue-store."""
    if living_doc_write_banned(root):
        return pii.project_index_status(
            root, prd, status, slug=slug, dry_run=dry_run, force_issue_store=True
        )
    return pii.project_index_status(root, prd, status, slug=slug, dry_run=dry_run)


def facade_gap_resolve(root: Path, prd: str, *, pr: str = "") -> dict[str, object]:
    """Route gap resolve through issue-store facade under issue-store."""
    if living_doc_write_banned(root):
        import gap_backlog

        return gap_backlog._resolve_for_prd_issue_store(root, prd)
    args: list[str] = ["gap-resolve", "--absorbing-prd", prd]
    if pr:
        args.extend(["--pr", pr])
    return run_reconcile_script(root, *args)


def gap_closeout_retry_config(root: Path) -> dict[str, float | int]:
    """Bounded retry budget for issue-search gap closeout (PRD 337 R11)."""
    from host_lib import load_workflow_config

    cfg = load_workflow_config(root)
    deliver = cfg.get("deliver") if isinstance(cfg.get("deliver"), dict) else {}
    living = deliver.get("livingDocs") if isinstance(deliver.get("livingDocs"), dict) else {}
    retry = living.get("gapCloseoutRetry") if isinstance(living.get("gapCloseoutRetry"), dict) else {}
    return {
        "maxAttempts": int(retry.get("maxAttempts", GAP_CLOSEOUT_RETRY_MAX_ATTEMPTS)),
        "baseBackoffSeconds": float(retry.get("baseBackoffSeconds", GAP_CLOSEOUT_RETRY_BASE_SECONDS)),
        "capBackoffSeconds": float(retry.get("capBackoffSeconds", GAP_CLOSEOUT_RETRY_CAP_SECONDS)),
    }


def _gap_resolve_resume_command(root: Path, worktree: Path) -> str:
    wt = worktree.resolve()
    repo = root.resolve()
    if wt != repo:
        return f"python3 scripts/wave.py living-docs reconcile --commit --orchestrator-worktree {wt}"
    return "python3 scripts/wave.py living-docs reconcile --commit"


def _gap_resolve_rate_limited_result(result: dict[str, Any]) -> bool:
    error = str(result.get("error") or "").lower()
    if error in {"rate-limited", "rate limit exceeded"}:
        return True
    if "rate" in error and "limit" in error:
        return True
    reason = str(result.get("reason") or "").lower()
    if reason in {"rate-limited", "cumulative-wait-exhausted"}:
        return True
    if result.get("retryable") is True and "rate" in error:
        return True
    return False


def _gap_resolve_rate_limited_exception(exc: BaseException) -> bool:
    from issues_lib import IssueRateLimited

    return isinstance(exc, IssueRateLimited)


def _gap_resolve_backoff_seconds(attempt: int, config: dict[str, float | int]) -> float:
    base = float(config["baseBackoffSeconds"])
    cap = float(config["capBackoffSeconds"])
    exp = min(cap, base * (2 ** max(0, attempt - 1)))
    return random.uniform(0.0, exp)


def _enforce_closeout_worktree(root: Path, worktree: Path) -> None:
    """Gap closeout must run from a non-default closeout worktree (PRD 337 R11)."""
    from default_branch_commit_guard import check

    result = check(root, worktree=worktree)
    if result.get("verdict") == "fail":
        fail(
            str(result.get("error") or "closeout worktree refused"),
            exit_code=20,
            halt="default-branch-closeout-refused",
            **{k: v for k, v in result.items() if k not in {"verdict", "error"}},
        )


def facade_gap_resolve_with_retry(
    root: Path,
    prd: str,
    *,
    worktree: Path,
    state: dict[str, Any] | None = None,
    pr: str = "",
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    """Bounded issue-search retry/backoff for gap closeout (PRD 337 R11)."""
    _enforce_closeout_worktree(root, worktree)
    config = gap_closeout_retry_config(root)
    max_attempts = int(config["maxAttempts"])
    resume_command = _gap_resolve_resume_command(root, worktree)
    attempts = 0
    cumulative_wait_ms = 0
    last_result: dict[str, Any] | None = None
    last_error = ""

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            result = facade_gap_resolve(worktree, prd, pr=pr)
            last_result = dict(result) if isinstance(result, dict) else {"verdict": "fail", "error": str(result)}
        except Exception as exc:  # noqa: BLE001 — classify retryable transport failures
            if not _gap_resolve_rate_limited_exception(exc):
                raise
            last_error = str(exc)
            last_result = {
                "verdict": "resolution-partial",
                "error": "rate-limited",
                "reason": getattr(exc, "reason", "rate-limited"),
                "retryable": bool(getattr(exc, "retryable", True)),
                "cumulativeWaitMs": getattr(exc, "cumulative_wait_ms", 0),
            }
        else:
            verdict = str(last_result.get("verdict") or "")
            if verdict == "pass":
                last_result["gapCloseoutRetry"] = {
                    "attempts": attempts,
                    "cumulativeWaitMs": cumulative_wait_ms,
                    "exhausted": False,
                }
                return last_result
            if not _gap_resolve_rate_limited_result(last_result):
                last_result["gapCloseoutRetry"] = {
                    "attempts": attempts,
                    "cumulativeWaitMs": cumulative_wait_ms,
                    "exhausted": False,
                }
                return last_result
            last_error = str(last_result.get("error") or "rate-limited")

        if attempt >= max_attempts:
            break
        wait_s = _gap_resolve_backoff_seconds(attempt, config)
        cumulative_wait_ms += int(wait_s * 1000)
        sleep_fn(wait_s)

    exhaustion: dict[str, Any] = {
        "verdict": "gap-closeout-retry-exhausted",
        "halt": "gap-closeout-retry-exhausted",
        "error": last_error or "gap closeout retry budget exhausted",
        "retryable": True,
        "attempts": attempts,
        "maxAttempts": max_attempts,
        "cumulativeWaitMs": cumulative_wait_ms,
        "resumeCommand": resume_command,
        "gapCloseoutRetry": {
            "attempts": attempts,
            "maxAttempts": max_attempts,
            "cumulativeWaitMs": cumulative_wait_ms,
            "exhausted": True,
        },
    }
    if last_result is not None:
        exhaustion["lastGapResolve"] = last_result
    from halt_resume import build_halt_resume

    exhaustion["haltResume"] = build_halt_resume(
        root,
        state,
        halt_cause="gap-closeout-retry-exhausted",
        resume_command=resume_command,
    )
    return exhaustion


def facade_append_completion(
    root: Path,
    *,
    prd: str,
    unit_id: str,
    phase: str,
    notes: str = "",
    pr: str = "",
    sha: str = "",
) -> dict[str, object]:
    """Route completion append through store events under issue-store."""
    if living_doc_write_banned(root):
        return append_completion_store_event(
            root,
            prd_id=prd,
            unit_id=unit_id,
            status="complete",
            evidence={"phase": phase, "notes": notes, "pr": pr, "sha": sha},
        )
    append_args = [
        "append-log-idempotent",
        "--prd",
        prd,
        "--phase",
        phase,
        "--notes",
        notes,
    ]
    if pr:
        append_args.extend(["--pr", pr])
    if sha:
        append_args.extend(["--sha", sha])
    return run_reconcile_script(root, *append_args)


def doctor_banned_living_path_drift(root: Path) -> dict[str, object]:
    """PRD 061 R3: fail when tracked living-doc paths are dirty under issue-store."""
    if not living_doc_write_banned(root):
        return {"verdict": "pass", "action": "doctor-banned-living-paths", "skipped": True}
    worktree = planning_paths.git_root(root)
    proc = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain", "--", *living_paths(worktree)],
        text=True,
        capture_output=True,
    )
    dirty = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if dirty:
        return {
            "verdict": "fail",
            "action": "doctor-banned-living-paths",
            "halt": "banned-living-doc-drift",
            "error": "tracked living-doc paths mutated under issue-store",
            "paths": dirty,
        }
    return {"verdict": "pass", "action": "doctor-banned-living-paths", "checks": ["banned-living-paths-clean"]}


def cmd_reconcile(root: Path, args: list[str]) -> None:
    if has_flag(args, "--commit") and not has_flag(args, "--dry-run"):
        worktree = resolve_worktree(root, args)
        _enforce_default_branch_commit_guard(root, worktree)
        _enforce_deliver_cwd_guard()
    from wave_living_doc_lock import living_doc_write_lock

    state = load_state(root)
    plan = load_plan(root, state)
    prd = prd_number_from_state(state, plan)
    if not prd:
        fail("prd_number missing from deliver state/plan")

    target = (state.get("target") or {}).get("branch")
    with living_doc_write_lock(root, target=target, holder="living-docs-reconcile"):
        _cmd_reconcile_locked(root, args, state, plan, prd)


def _cmd_reconcile_locked(
    root: Path, args: list[str], state: dict[str, Any], plan: dict[str, Any], prd: str
) -> None:
    merged_main = target_merge_detected(root, state)
    index_status = derive_index_status(state, merged_main)
    worktree = resolve_worktree(root, args)
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")

    slug = str((state.get("target") or {}).get("slug") or plan.get("slug") or "")
    if living_doc_write_banned(worktree):
        index_out = facade_set_index_status(
            worktree,
            prd,
            index_status,
            slug=slug or None,
            dry_run=dry_run,
        )
    else:
        issue_projection = pii.project_index_status(
            worktree,
            prd,
            index_status,
            slug=slug or None,
            dry_run=dry_run,
        )
        if issue_projection.get("verdict") == "skipped":
            index_out = run_reconcile_script(
                worktree,
                "set-index-status",
                "--prd",
                prd,
                "--status",
                index_status,
            )
        else:
            index_out = issue_projection


    planning_graph_out: dict[str, Any] | None = None
    legacy: dict[str, Any] | None = None
    dirs = planning_paths.load_planning_dirs(root)
    if dirs.planning == "docs/planning":
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "planning_graph.py"), str(worktree), "reconcile", "--dry-run"],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0 and proc.stdout.strip().startswith("{"):
            planning_graph_out = json.loads(proc.stdout)
        # Reconcile updates living INDEX/GAP-BACKLOG via set-index-status + gap-resolve only.
        # Legacy projection emits a sparse shim and must not run here (pre-cutover prdsDir corpus).

    gap_out: dict[str, Any] | None = None
    if index_status == "complete":
        pr_ref = ""
        terminal = state.get("terminalPr") or {}
        if terminal.get("number"):
            pr_ref = str(terminal["number"])
        gap_out = facade_gap_resolve_with_retry(
            root,
            prd,
            worktree=worktree,
            state=state,
            pr=pr_ref if not living_doc_write_banned(worktree) else "",
        )

    if gap_out and gap_out.get("verdict") == "gap-closeout-retry-exhausted":
        fail(
            str(gap_out.get("error") or "gap closeout retry budget exhausted"),
            exit_code=30,
            halt="gap-closeout-retry-exhausted",
            action="living-docs-reconcile",
            prd=prd,
            indexStatus=index_status,
            mergedCompleteRefused=True,
            gapResolve=gap_out,
            haltResume=gap_out.get("haltResume"),
            resumeCommand=gap_out.get("resumeCommand"),
        )

    commit_sha = None
    if do_commit and not dry_run:
        commit_sha = git_commit_living_docs(worktree, prd, dry_run=False)

    emit(
        {
            "verdict": "pass",
            "action": "living-docs-reconcile",
            "prd": prd,
            "indexStatus": index_status,
            "mergedToMain": merged_main,
            "index": index_out,
            "gapResolve": gap_out,
            "planningGraphReconcile": planning_graph_out,
            "legacyProjection": legacy if dirs.planning == "docs/planning" else None,
            "livingDocsCommit": commit_sha,
            "dryRun": dry_run,
        }
    )


def cmd_append_terminal(root: Path, args: list[str]) -> None:
    """Idempotent COMPLETION-LOG append when all phases are green (R48)."""
    if has_flag(args, "--commit") and not has_flag(args, "--dry-run"):
        worktree = resolve_worktree(root, args)
        _enforce_default_branch_commit_guard(root, worktree)
        _enforce_deliver_cwd_guard()
    from wave_living_doc_lock import living_doc_write_lock

    state = load_state(root)
    target = (state.get("target") or {}).get("branch")
    with living_doc_write_lock(root, target=target, holder="living-docs-append-terminal"):
        _cmd_append_terminal_locked(root, args, state)


def _cmd_append_terminal_locked(root: Path, args: list[str], state: dict[str, Any]) -> None:
    plan = load_plan(root, state)
    prd = prd_number_from_state(state, plan)
    if not prd:
        fail("prd_number missing from deliver state/plan")

    from wave_state import phase_complete

    phases = state.get("phases") or {}
    if phases and not all(phase_complete((meta or {}).get("status")) for meta in phases.values()):
        fail("not all phases terminal-complete; skip terminal append", exit_code=10)

    worktree = resolve_worktree(root, args)
    phase = parse_kv(args, "--phase") or "all"
    notes = parse_kv(args, "--notes") or "deliver complete — awaiting terminal merge"
    pr = parse_kv(args, "--pr") or ""
    terminal = state.get("terminalPr") or {}
    if not pr and terminal.get("number"):
        pr = str(terminal["number"])

    top = worktree
    sha_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
    )
    head = sha_proc.stdout.strip() if sha_proc.returncode == 0 else ""

    append_args = [
        "append-log-idempotent",
        "--prd",
        prd,
        "--phase",
        phase,
        "--notes",
        notes,
    ]
    if pr:
        append_args.extend(["--pr", pr])
    if head:
        append_args.extend(["--sha", head])

    slug = str((state.get("target") or {}).get("slug") or plan.get("slug") or "")
    unit_id = pii.resolve_prd_unit_id(worktree, prd, slug=slug or None) or f"prd-{prd}"
    if living_doc_write_banned(worktree):
        out = facade_append_completion(
            worktree,
            prd=prd,
            unit_id=unit_id,
            phase=phase,
            notes=notes,
            pr=pr,
            sha=head,
        )
    else:
        out = run_reconcile_script(worktree, *append_args)
    commit_sha = None
    if has_flag(args, "--commit"):
        commit_sha = git_commit_living_docs(worktree, prd, dry_run=False)

    emit(
        {
            "verdict": "pass",
            "action": "living-docs-append-terminal",
            "append": out,
            "livingDocsCommit": commit_sha,
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_living_docs.py <root> <reconcile|append-terminal|regenerate-index|phase-status-live> [args...]")
    root = Path(sys.argv[1]).resolve()
    cmd = sys.argv[2]
    rest = sys.argv[3:]
    if cmd == "reconcile":
        cmd_reconcile(root, rest)
    elif cmd == "append-terminal":
        cmd_append_terminal(root, rest)
    elif cmd == "phase-status-live":
        cmd_phase_status_live(root, rest)
    elif cmd == "regenerate-index":
        cmd_regenerate_index(root, rest)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
