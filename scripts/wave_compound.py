#!/usr/bin/env python3
"""Pre-merge compounding and completion semantics for /sw-deliver (PRD 007 R17–R21, R31, R53)."""
from __future__ import annotations

import json
import os
import subprocess

from _sw import interpreter
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_invoke import host_verb

from cleanup_lib import load_default_branch
from wave_json_io import StateCorruptError, read_json, write_json
from wave_state import (
    branch_slug_from_target,
    completion_finalize_authorization,
    load_deliver_state,
    phase_complete,
    resolve_state_path,
    run_slug_from_state,
    save_deliver_state,
    slug_drift_payload,
    target_branch_from_state,
)

# File outputs safe to commit pre-merge (R18). Memory/provider artifacts are never committed (R19).
ALLOWED_PREMERGE_FILE_PREFIXES = (
    "docs/prds/COMPLETION-LOG.md",
    "docs/prds/INDEX.md",
    "CHANGELOG.md",
    "docs/learnings/",
    ".cursor/sw-deliver-state",
)

MEMORY_PATH_MARKERS = (
    ".cursor/memory/",
    "recallium",
    "memory-preflight",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def state_path(root: Path, state: dict[str, Any] | None = None) -> Path:
    return resolve_state_path(git_top(root), state_hint=state)


def load_state(root: Path) -> dict[str, Any]:
    top = git_top(root)
    return load_deliver_state(top)


def save_state(root: Path, state: dict[str, Any]) -> None:
    top = git_top(root)
    save_deliver_state(top, state)


def git_top(root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def current_branch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        text=True,
        capture_output=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def resolve_default_ref(top: Path, default: str) -> tuple[str, str]:
    """Prefer origin/<default> when present so worktrees detect merges without a local main update."""
    for ref in (f"origin/{default}", default):
        proc = subprocess.run(
            ["git", "-C", str(top), "rev-parse", ref],
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            sha = proc.stdout.strip()
            if sha:
                return ref, sha
    return default, ""


def _breadcrumb_target_branch(root: Path) -> str | None:
    legacy = root / ".cursor" / "sw-deliver-state.json"
    if not legacy.is_file():
        return None
    try:
        data = read_json(legacy)
    except StateCorruptError:
        return None
    from wave_state import _is_migration_breadcrumb

    if not _is_migration_breadcrumb(data):
        return target_branch_from_state(data)
    target = data.get("target")
    if isinstance(target, str) and target:
        return target
    return None


def resolve_target_branch(
    root: Path,
    state: dict[str, Any],
) -> tuple[str | None, str]:
    """Resolve target branch: run-scoped state → breadcrumb → terminal PR head."""
    branch = target_branch_from_state(state)
    if branch:
        return branch, "state"
    breadcrumb = _breadcrumb_target_branch(root)
    if breadcrumb:
        return breadcrumb, "breadcrumb"
    terminal = state.get("terminalPr") or {}
    for key in ("headRefName", "headBranch"):
        head = terminal.get(key)
        if isinstance(head, str) and head.strip():
            return head.strip(), f"terminalPr.{key}"
    return None, ""


def _terminal_pr_payload_from_view(payload: dict[str, Any], *, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    merge_commit = payload.get("mergeCommit") or {}
    head = payload.get("headRefName") or (fallback or {}).get("headRefName")
    return {
        "number": payload.get("number") or (fallback or {}).get("number"),
        "url": payload.get("url") or (fallback or {}).get("url"),
        "mergedAt": payload.get("mergedAt") or (fallback or {}).get("mergedAt"),
        "mergeCommit": merge_commit.get("oid") if isinstance(merge_commit, dict) else merge_commit,
        "headRefName": head,
    }


def merged_terminal_pr_by_head(root: Path, target: str) -> tuple[dict[str, Any] | None, bool]:
    """Discover merged terminal PR via host list when durable state is cleared (R13)."""
    top = git_top(root)
    default = load_default_branch(top)
    host_unavailable = False
    for state_filter in ("merged", "closed", "all"):
        out = host_verb(root, "pr-list", head=target, base=default, state=state_filter)
        if out.get("verdict") != "ok":
            host_unavailable = True
            continue
        items = out.get("data") if isinstance(out.get("data"), list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            pr_state = str(item.get("state") or "").upper()
            if pr_state and pr_state not in ("MERGED", "CLOSED"):
                continue
            number = item.get("number")
            if number is None:
                continue
            viewed = host_verb(root, "pr-view", number=str(number))
            if viewed.get("verdict") != "ok":
                host_unavailable = True
                continue
            payload = viewed.get("data") or {}
            if str(payload.get("state") or "").upper() != "MERGED":
                continue
            if payload.get("number") is None:
                payload = {**payload, "number": number}
            return _terminal_pr_payload_from_view(payload, fallback=item), host_unavailable
    return None, host_unavailable


def _host_indeterminate() -> dict[str, Any]:
    return {"merged": False, "status": "indeterminate", "detail": "host-unavailable"}


def terminal_pr_merged_via_host(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    """Authoritative merge signal for squash-merged terminal PRs (R53)."""
    terminal = state.get("terminalPr") or {}
    number = terminal.get("number")
    discovered: dict[str, Any] | None = None
    host_unavailable = False

    def _recover_by_head() -> dict[str, Any] | None:
        nonlocal discovered, host_unavailable
        target = resolve_target_branch(root, state)[0]
        if not target:
            return None
        discovered, host_unavailable = merged_terminal_pr_by_head(root, target)
        return discovered

    if number is not None:
        viewed = host_verb(root, "pr-view", number=str(number))
        if viewed.get("verdict") != "ok":
            recovered = _recover_by_head()
            if recovered:
                number = recovered.get("number")
            elif host_unavailable:
                return _host_indeterminate()
            else:
                return None
        else:
            payload = viewed.get("data") or {}
            if str(payload.get("state") or "").upper() != "MERGED":
                recovered = _recover_by_head()
                if recovered:
                    number = recovered.get("number")
                    discovered = recovered
                elif host_unavailable:
                    return _host_indeterminate()
                else:
                    return None
            else:
                merge_commit = payload.get("mergeCommit") or {}
                return {
                    "merged": True,
                    "status": "merged",
                    "detail": "terminal-pr-host",
                    "prNumber": number,
                    "mergedAt": payload.get("mergedAt"),
                    "mergeCommit": merge_commit.get("oid") if isinstance(merge_commit, dict) else merge_commit,
                }
    else:
        discovered = _recover_by_head()
        if discovered:
            number = discovered.get("number")
        elif host_unavailable:
            return _host_indeterminate()
        else:
            return None

    if discovered and number is not None:
        return {
            "merged": True,
            "status": "merged",
            "detail": "terminal-pr-host-recovered",
            "prNumber": number,
            "mergedAt": discovered.get("mergedAt"),
            "mergeCommit": discovered.get("mergeCommit"),
        }

    out = host_verb(root, "pr-view", number=str(number))
    if out.get("verdict") != "ok":
        return _host_indeterminate()
    payload = out.get("data") or {}
    if str(payload.get("state") or "").upper() != "MERGED":
        return None
    merge_commit = payload.get("mergeCommit") or {}
    return {
        "merged": True,
        "status": "merged",
        "detail": "terminal-pr-host",
        "prNumber": number,
        "mergedAt": payload.get("mergedAt"),
        "mergeCommit": merge_commit.get("oid") if isinstance(merge_commit, dict) else merge_commit,
    }


def enrich_state_for_merge_check(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Recover target/terminalPr hints when branch-scoped state was cleared (R13/R14)."""
    enriched = dict(state)
    target, target_source = resolve_target_branch(root, enriched)
    if target and not target_branch_from_state(enriched):
        enriched.setdefault("target", {})["branch"] = target
    terminal = dict(enriched.get("terminalPr") or {})
    needs_recovery = not terminal.get("number")
    if terminal.get("number") is not None and not needs_recovery:
        viewed = host_verb(root, "pr-view", number=str(terminal["number"]))
        if viewed.get("verdict") == "ok":
            payload = viewed.get("data") or {}
            if str(payload.get("state") or "").upper() != "MERGED":
                needs_recovery = True
    if needs_recovery and target:
        discovered, _host_unavailable = merged_terminal_pr_by_head(root, target)
        if discovered:
            enriched["terminalPr"] = discovered
            if not target_branch_from_state(enriched):
                head = discovered.get("headRefName")
                if isinstance(head, str) and head:
                    enriched.setdefault("target", {})["branch"] = head
    elif terminal:
        enriched["terminalPr"] = terminal
    enriched["_targetSource"] = target_source
    return enriched


def _attach_slug_drift(
    result: dict[str, Any],
    state: dict[str, Any],
    target: str | None,
    *,
    source: str,
) -> dict[str, Any]:
    drift = slug_drift_payload(run_slug_from_state(state), target, source=source)
    if drift:
        result = {**result, "slugDrift": drift}
    return result


def target_merge_detected(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    work_state = enrich_state_for_merge_check(root, state)
    target, target_source = resolve_target_branch(root, work_state)
    if not target:
        return {"merged": False, "reason": "no-target-branch"}
    top = git_top(root)
    default = load_default_branch(top)

    gh_info = terminal_pr_merged_via_host(root, work_state)
    host_indeterminate = bool(gh_info and gh_info.get("status") == "indeterminate")
    if gh_info and gh_info.get("merged"):
        return _attach_slug_drift(
            {**gh_info, "target": target, "default": default},
            state,
            target,
            source=target_source,
        )

    target_proc = subprocess.run(
        ["git", "-C", str(top), "rev-parse", target],
        text=True,
        capture_output=True,
    )
    target_sha = target_proc.stdout.strip() if target_proc.returncode == 0 else ""
    default_ref, default_sha = resolve_default_ref(top, default)
    if not target_sha or not default_sha:
        base = {
            "merged": False,
            "status": "indeterminate",
            "detail": "missing-branch-ref",
            "target": target,
            "default": default,
            "defaultRef": default_ref,
        }
        if host_indeterminate:
            base["detail"] = "host-unavailable"
        return _attach_slug_drift(base, state, target, source=target_source)
    anc = subprocess.run(
        ["git", "-C", str(top), "merge-base", "--is-ancestor", target_sha, default_sha],
        capture_output=True,
    )
    if anc.returncode == 0:
        return _attach_slug_drift(
            {
                "merged": True,
                "status": "merged",
                "detail": "ancestor-of-default",
                "target": target,
                "default": default,
                "defaultRef": default_ref,
            },
            state,
            target,
            source=target_source,
        )
    cherry = subprocess.run(
        ["git", "-C", str(top), "cherry", default_ref, target],
        text=True,
        capture_output=True,
    )
    plus = [ln for ln in cherry.stdout.splitlines() if ln.startswith("+")]
    if cherry.returncode == 0 and not plus and cherry.stdout.strip():
        return _attach_slug_drift(
            {
                "merged": True,
                "status": "merged",
                "detail": "squash-cherry",
                "target": target,
                "default": default,
                "defaultRef": default_ref,
            },
            state,
            target,
            source=target_source,
        )
    if host_indeterminate:
        return _attach_slug_drift(
            {
                "merged": False,
                "status": "indeterminate",
                "detail": "host-unavailable",
                "target": target,
                "default": default,
                "defaultRef": default_ref,
            },
            state,
            target,
            source=target_source,
        )
    return _attach_slug_drift(
        {
            "merged": False,
            "status": "unmerged",
            "detail": "not-on-default",
            "target": target,
            "default": default,
            "defaultRef": default_ref,
        },
        state,
        target,
        source=target_source,
    )


def is_allowed_premerge_path(path: str) -> bool:
    if any(marker in path for marker in MEMORY_PATH_MARKERS):
        return False
    return any(path == p or path.startswith(p) for p in ALLOWED_PREMERGE_FILE_PREFIXES)


def changed_files(root: Path, base: str = "HEAD") -> list[str]:
    top = git_top(root)
    files: list[str] = []
    for cmd in (
        ["git", "-C", str(top), "diff", "--name-only", base],
        ["git", "-C", str(top), "diff", "--cached", "--name-only"],
    ):
        proc = subprocess.run(cmd, text=True, capture_output=True)
        if proc.returncode == 0:
            files.extend(ln.strip() for ln in proc.stdout.splitlines() if ln.strip())
    return sorted(set(files))


def load_workflow_config(root: Path) -> dict[str, Any]:
    from shipwright_paths import load_workflow_config as _load_workflow_config

    return _load_workflow_config(root)
def compound_autonomy_mode(root: Path) -> str:
    cfg = load_workflow_config(root)
    compound = cfg.get("compound") or {}
    mode = compound.get("autonomy", "supervised")
    return mode if mode in ("supervised", "auto") else "supervised"


def cmd_retrospective_autonomy(root: Path, _args: list[str]) -> None:
    mode = compound_autonomy_mode(root)
    emit(
        {
            "verdict": "pass",
            "action": "retrospective-autonomy",
            "mode": mode,
            "promptGates": mode == "supervised",
            "safetyGates": {
                "memoryFailClosed": True,
                "ruleClassHumanGated": True,
            },
            "note": "autonomy gates approval prompts only (R10); R7/R8 safety gates always apply",
        }
    )


def all_phases_green(state: dict[str, Any]) -> bool:
    phases = state.get("phases") or {}
    if not phases:
        return False
    return all(phase_complete(p.get("status")) for p in phases.values())


def detect_retrospective_phase(root: Path, state: dict[str, Any]) -> str:
    """Deterministic phase from deliver run-state + merge status (R2)."""
    merge_info = target_merge_detected(root, state)
    if merge_info.get("merged"):
        return "post-merge"
    compound = state.get("compoundShip") or {}
    completion = state.get("completion") or {}
    if completion.get("status") == "completed-pending-merge":
        return "post-merge"
    if compound.get("premergeDone"):
        return "post-merge"
    if state.get("phases") and all_phases_green(state):
        return "pre-merge"
    if state.get("terminalPr"):
        return "pre-merge"
    if target_branch_from_state(state):
        return "pre-merge"
    return "post-merge"


def cmd_retrospective_detect_phase(root: Path, _args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    phase = detect_retrospective_phase(root, state)
    merge_info = target_merge_detected(root, state) if state else {"merged": False}
    emit(
        {
            "verdict": "pass",
            "action": "retrospective-detect-phase",
            "phase": phase,
            "invoke": f"/sw-retrospective --{phase}",
            "mergeDetected": merge_info.get("merged"),
            "premergeDone": bool((state.get("compoundShip") or {}).get("premergeDone")),
        }
    )


def cmd_compound_premerge_env(root: Path, args: list[str], *, domain: str = "retrospective") -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    target = (state.get("target") or {}).get("branch", "<type>/<slug>")
    invoke = (
        "/sw-compound-ship --pre-merge"
        if domain == "compound-ship"
        else "/sw-retrospective --pre-merge"
    )
    record_cmd = (
        "bash scripts/wave.py compound-ship record-premerge --prd <n> --phase <name>"
        if domain == "compound-ship"
        else "bash scripts/wave.py retrospective record-premerge --prd <n> --phase <name>"
    )
    emit(
        {
            "verdict": "pass",
            "action": (
                "compound-ship-premerge-env"
                if domain == "compound-ship"
                else "retrospective-premerge-env"
            ),
            "invoke": invoke,
            "targetBranch": target,
            "fileOutputsCommit": True,
            "memoryCommit": False,
            "reconcileFlags": ["--require-merge"],
            "recordCommand": record_cmd,
            "guardrails": {
                "ruleClassPromotion": "human-gated-only",
                "memoryProviderUnreachable": "fail-closed",
                "compoundAutonomy": compound_autonomy_mode(root),
            },
        }
    )


def cmd_compound_record_premerge(root: Path, args: list[str]) -> None:
    import deliver_cwd_guard

    deliver_cwd_guard.enforce()
    prd = parse_kv(args, "--prd")
    phase = parse_kv(args, "--phase") or "deliver"
    notes = parse_kv(args, "--notes") or "pre-merge compounding complete"
    if not prd:
        fail("--prd required (e.g. 007)")
    state = load_state(root)
    now = utc_now()
    state["compoundShip"] = {
        "premergeDone": True,
        "mode": "pre-merge",
        "at": now,
        "prd": prd,
        "phase": phase,
        "ruleClassPromotion": "human-gated",
    }
    state["completion"] = {
        "status": "completed-pending-merge",
        "at": now,
        "prd": prd,
        "phase": phase,
        "notes": notes,
    }
    save_state(root, state)
    if not has_flag(args, "--skip-append-log"):
        from _sw.completion_log import append_log_idempotent
        append_log_idempotent(root, prd=prd, phase=phase, notes=notes)
    emit(
        {
            "verdict": "pass",
            "action": "compound-ship-record-premerge",
            "completion": state["completion"],
            "compoundShip": state["compoundShip"],
        }
    )


def cmd_compound_check_file_outputs(root: Path, args: list[str]) -> None:
    """Verify working tree / last commit touches only allowed pre-merge file paths."""
    base = parse_kv(args, "--base") or "HEAD"
    top = git_top(root)
    files = changed_files(top, base)
    if not files and base == "HEAD":
        files = changed_files(top, "HEAD~1..HEAD")
    disallowed = [f for f in files if not is_allowed_premerge_path(f)]
    memory_like = [f for f in files if any(m in f for m in MEMORY_PATH_MARKERS)]
    if disallowed or memory_like:
        emit(
            {
                "verdict": "fail",
                "error": "pre-merge file outputs include disallowed paths",
                "disallowed": disallowed,
                "memoryLike": memory_like,
                "allowedPrefixes": list(ALLOWED_PREMERGE_FILE_PREFIXES),
            },
            exit_code=1,
        )
    emit(
        {
            "verdict": "pass",
            "action": "compound-ship-check-file-outputs",
            "files": files,
            "memoryCommitted": False,
        }
    )


def cmd_completion_check_merge(root: Path, _args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    info = target_merge_detected(root, state)
    emit({"verdict": "pass", "action": "completion-check-merge", **info})


def invoke_living_docs_reconcile_finalize(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    """PRD 046 A2 hook at finalize — feature-detected fallback when entrypoint missing (R15)."""
    script = SCRIPT_DIR / "wave_living_docs.py"
    if not script.is_file():
        return {"skipped": True, "reason": "wave_living_docs.py missing", "crossLink": "PRD 046 A2"}
    cmd = [sys.executable, str(script), str(root), "reconcile", "--commit"]
    orch = (state.get("orchestratorWorktree") or {}).get("path")
    if orch:
        cmd.extend(["--orchestrator-worktree", str(orch)])
    proc = subprocess.run(
        cmd,
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode in (0, 10):
        try:
            return json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return {"verdict": "pass", "raw": proc.stdout.strip()}
    try:
        err = json.loads(proc.stdout or proc.stderr or "{}")
    except json.JSONDecodeError:
        err = {"error": proc.stderr.strip() or proc.stdout.strip() or "living-docs reconcile failed"}
    return {
        "skipped": True,
        "reason": err.get("error", "living-docs reconcile failed"),
        "crossLink": "PRD 046 A2",
        "exitCode": proc.returncode,
    }


def _persist_finalize_state(root: Path, state: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    completion = dict(state.get("completion") or {})
    completion.update(
        {
            "status": "merged-complete",
            "mergedAt": info.get("mergedAt") or now,
            "mergeDetail": info.get("detail"),
        }
    )
    if info.get("prNumber") is not None:
        completion["prNumber"] = info["prNumber"]
    if info.get("mergeCommit"):
        completion["mergeCommit"] = info["mergeCommit"]
    if not completion.get("at"):
        completion["at"] = now
    state["completion"] = completion
    state["verdict"] = "complete"
    target = target_branch_from_state(state) or info.get("target")
    if target:
        slug = branch_slug_from_target(target)
        state["target"] = {"branch": target, "slug": slug}
        completion["slug"] = slug
    if info.get("prNumber") is not None:
        terminal = dict(state.get("terminalPr") or {})
        terminal["number"] = info["prNumber"]
        if info.get("mergeCommit"):
            terminal["mergeCommit"] = info["mergeCommit"]
        if info.get("mergedAt"):
            terminal["mergedAt"] = info["mergedAt"]
        if target:
            terminal["headRefName"] = target
        state["terminalPr"] = terminal
    with completion_finalize_authorization():
        save_state(root, state)
    return completion


def cmd_completion_finalize_if_merged(root: Path, args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    completion = state.get("completion") or {}
    if completion.get("status") == "merged-complete" and state.get("verdict") == "complete":
        work_state = enrich_state_for_merge_check(root, state)
        info = target_merge_detected(root, work_state)
        emit(
            {
                "verdict": "pass",
                "action": "completion-finalize",
                "idempotent": True,
                "cleanupSuggestion": "Run `/sw-cleanup` to prune merged branches and stale worktrees.",
                "completion": completion,
                "mergeDetected": info,
            }
        )
        return
    work_state = enrich_state_for_merge_check(root, state)
    info = target_merge_detected(root, work_state)
    if not info.get("merged"):
        completion = work_state.get("completion") or {}
        if completion.get("status") != "completed-pending-merge":
            fail(
                "completion not in completed-pending-merge state and host merge not detected",
                exit_code=10 if completion else 2,
                halt="wait" if completion else "blocked",
                **info,
            )
        fail(
            "target branch not merged — cannot finalize completion",
            exit_code=10,
            halt="wait",
            **info,
        )
    living_docs = invoke_living_docs_reconcile_finalize(root, work_state)
    if state:
        merged_state = dict(state)
        if work_state.get("terminalPr"):
            merged_state["terminalPr"] = work_state["terminalPr"]
        if work_state.get("target"):
            merged_state["target"] = work_state["target"]
        completion = _persist_finalize_state(root, merged_state, info)
    else:
        completion = {
            "status": "merged-complete",
            "mergedAt": utc_now(),
            "mergeDetail": info.get("detail"),
            "persistSkipped": True,
            "reason": "durable-state-cleared",
        }
    payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "completion-finalize",
        "cleanupSuggestion": "Run `/sw-cleanup` to prune merged branches and stale worktrees.",
        "completion": completion,
        "mergeDetected": info,
    }
    if living_docs is not None:
        payload["livingDocsReconcile"] = living_docs
    emit(payload)


def cmd_completion_status(root: Path, _args: list[str]) -> None:
    state = load_state(root) if state_path(root).is_file() else {}
    completion = state.get("completion") or {}
    compound = state.get("compoundShip") or {}
    merge_info = target_merge_detected(root, state) if state else {"merged": False}
    terminal_complete = (
        completion.get("status") == "merged-complete"
        or (state.get("verdict") == "complete" and merge_info.get("merged"))
    )
    emit(
        {
            "verdict": "pass",
            "action": "completion-status",
            "completion": completion or None,
            "compoundShip": compound or None,
            "mergeDetected": merge_info.get("merged"),
            "reportsComplete": terminal_complete,
            "cleanupSuggestion": (
                "Run `/sw-cleanup` to prune merged branches and stale worktrees."
                if merge_info.get("merged")
                else None
            ),
        }
    )


def _compound_ship_subcommands(root: Path, sub: str, rest: list[str], *, domain: str) -> None:
    if sub in ("premerge-env", "env"):
        cmd_compound_premerge_env(root, rest, domain=domain)
    elif sub in ("record-premerge", "record"):
        cmd_compound_record_premerge(root, rest)
    elif sub in ("check-file-outputs", "check-files"):
        cmd_compound_check_file_outputs(root, rest)
    elif sub in ("detect-phase", "detect"):
        cmd_retrospective_detect_phase(root, rest)
    elif sub in ("autonomy", "autonomy-mode"):
        cmd_retrospective_autonomy(root, rest)
    else:
        fail(
            "subcommand: premerge-env|record-premerge|check-file-outputs|detect-phase|autonomy"
        )


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: wave_compound.py <root> <compound-ship|retrospective|completion> <subcommand> [args...]"
        )
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain in ("compound-ship", "retrospective"):
        sub = args[0] if args else ""
        rest = args[1:]
        _compound_ship_subcommands(root, sub, rest, domain=domain)
    elif domain == "completion":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "check-merge":
            cmd_completion_check_merge(root, rest)
        elif sub == "finalize-if-merged":
            cmd_completion_finalize_if_merged(root, rest)
        elif sub == "status":
            cmd_completion_status(root, rest)
        else:
            fail("completion subcommand: check-merge|finalize-if-merged|status")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
