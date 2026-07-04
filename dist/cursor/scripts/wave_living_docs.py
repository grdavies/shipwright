#!/usr/bin/env python3
"""Living-doc reconciliation for /sw-deliver (R47–R51): INDEX, COMPLETION-LOG, GAP-BACKLOG."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_paths
VALID_INDEX_STATUSES = frozenset({"not-started", "in-progress", "complete"})
TERMINAL_PHASE_STATUSES = frozenset({"green-merged", "teardown-pending", "teardown-complete"})

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


def load_plan(root: Path) -> dict[str, Any]:
    path = root / ".cursor" / "sw-deliver-plan.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


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


def cmd_reconcile(root: Path, args: list[str]) -> None:
    if has_flag(args, "--commit") and not has_flag(args, "--dry-run"):
        worktree = resolve_worktree(root, args)
        _enforce_default_branch_commit_guard(root, worktree)
        _enforce_deliver_cwd_guard()
    from wave_living_doc_lock import living_doc_write_lock

    state = load_state(root)
    plan = load_plan(root)
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

    index_out = run_reconcile_script(
        worktree,
        "set-index-status",
        "--prd",
        prd,
        "--status",
        index_status,
    )


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
        gap_out = run_reconcile_script(
            worktree,
            "gap-resolve",
            "--absorbing-prd",
            prd,
            *(["--pr", pr_ref] if pr_ref else []),
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
    plan = load_plan(root)
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
