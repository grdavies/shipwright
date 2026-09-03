#!/usr/bin/env python3
"""Shared phase status discovery chain (PRD 059 R5/R6, PRD 081 R20)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from status_integrity import resolve_status_candidates
from wave_json_io import StateCorruptError, read_json

TiebreakFn = Callable[[list[tuple[Path, dict[str, Any]]]], tuple[Path, dict[str, Any]] | None]


def _load_deliver_state(root: Path, state: dict[str, Any] | None) -> dict[str, Any]:
    if state is not None:
        return state
    try:
        from wave_state import load_deliver_state

        return load_deliver_state(root)
    except Exception:
        return {}


def resolve_phase_worktree(
    root: Path, phase_slug: str, state: dict[str, Any]
) -> Path | None:
    phases = state.get("phases") or {}
    phase_id: str | None = None
    for pid, meta in phases.items():
        if isinstance(meta, dict) and meta.get("slug") == phase_slug:
            phase_id = str(pid)
            break
    if not phase_id:
        return None
    wt_info = (state.get("phaseWorktrees") or {}).get(phase_id) or {}
    if not isinstance(wt_info, dict):
        return None
    raw = wt_info.get("path")
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_absolute():
        path = (root / path).resolve()
    return path if path.is_dir() else None


def resolve_run_and_phase_id(
    state: dict[str, Any], phase_slug: str
) -> tuple[str, str] | None:
    """Resolve explicit run id + stable phase id; slug is display-only lookup (R20).

    Synthetic run ids (branch-derived) must not drive discovery — they invent
    empty run-scoped paths while fixtures still write slug-keyed artifacts.
    """
    run_id = state.get("runId") or state.get("scopedRunId")
    if not run_id or not str(run_id).strip():
        return None
    for pid, meta in (state.get("phases") or {}).items():
        if isinstance(meta, dict) and meta.get("slug") == phase_slug:
            return str(run_id).strip(), str(pid)
    return None


def canonical_phase_artifact_path(
    root: Path, run_id: str, phase_id: str, status_filename: str
) -> Path:
    from wave_run_paths import phase_directory

    return phase_directory(root, run_id, phase_id) / status_filename


def worktree_mirror_path(root: Path, worktree: Path, canonical: Path) -> Path:
    """Map a canonical status path into a phase worktree mirror.

    When deliver-loop cwd is the orchestrator worktree, run-scoped status may
    live under the primary repo (R28 ``path_normalize_anchor``). Relativize
    against that anchor so discovery does not raise ``ValueError``.
    """
    canon = canonical.resolve()
    try:
        rel = canon.relative_to(root.resolve())
    except ValueError:
        from wave_state import path_normalize_anchor

        try:
            rel = canon.relative_to(path_normalize_anchor(root))
        except ValueError:
            return canon
    return (worktree / rel).resolve()


def _legacy_slug_candidate_paths(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None,
    state: dict[str, Any],
) -> list[Path]:
    """Pre-run / non-run-scoped discovery: slug paths only — never glob (R20)."""
    paths: list[Path] = [
        root / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename
    ]
    wt = worktree
    if wt is None:
        wt = resolve_phase_worktree(root, phase_slug, state)
    if wt is not None:
        paths.append(
            wt / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename
        )
    return paths


def collect_status_candidate_paths(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None = None,
    state: dict[str, Any] | None = None,
) -> list[Path]:
    """Discovery: run-scoped paths when runId is set; else legacy slug paths (no glob)."""
    loaded = _load_deliver_state(root, state)
    resolved = resolve_run_and_phase_id(loaded, phase_slug)
    if resolved is None:
        return _legacy_slug_candidate_paths(
            root, phase_slug, status_filename, worktree=worktree, state=loaded
        )
    run_id, phase_id = resolved
    canonical = canonical_phase_artifact_path(root, run_id, phase_id, status_filename)
    paths: list[Path] = [canonical]
    wt = worktree
    if wt is None:
        wt = resolve_phase_worktree(root, phase_slug, loaded)
    if wt is not None:
        paths.append(worktree_mirror_path(root, wt, canonical))
    return paths


def load_status_candidates(
    candidate_paths: list[Path],
) -> list[tuple[Path, dict[str, Any]]]:
    seen: set[str] = set()
    loaded: list[tuple[Path, dict[str, Any]]] = []
    for path in candidate_paths:
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        if not path.is_file():
            continue
        try:
            loaded.append((path, read_json(path)))
        except (StateCorruptError, json.JSONDecodeError, OSError):
            continue
    return loaded


def discover_phase_status(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None = None,
    expected_head: str | None = None,
    tiebreak: TiebreakFn | None = None,
    state: dict[str, Any] | None = None,
) -> tuple[Path | None, dict[str, Any] | None]:
    candidates = load_status_candidates(
        collect_status_candidate_paths(
            root, phase_slug, status_filename, worktree=worktree, state=state
        )
    )
    if not candidates:
        return None, None
    if tiebreak is not None:
        picked = tiebreak(candidates)
        if picked is not None:
            return picked
    return resolve_status_candidates(candidates, expected_head)


def preferred_phase_artifact_path(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None = None,
    state: dict[str, Any] | None = None,
) -> Path:
    """Preferred write path: worktree mirror when present, else run-scoped canonical."""
    loaded = _load_deliver_state(root, state)
    resolved = resolve_run_and_phase_id(loaded, phase_slug)
    if resolved is None:
        return root / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename
    run_id, phase_id = resolved
    canonical = canonical_phase_artifact_path(root, run_id, phase_id, status_filename)
    wt = worktree
    if wt is None:
        wt = resolve_phase_worktree(root, phase_slug, loaded)
    if wt is not None:
        mirror = worktree_mirror_path(root, wt, canonical)
        if mirror.is_file():
            return mirror
    return canonical


def first_existing_status_path(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None = None,
    state: dict[str, Any] | None = None,
) -> Path:
    """Return the preferred on-disk path for a phase status artifact."""
    for candidate in collect_status_candidate_paths(
        root, phase_slug, status_filename, worktree=worktree, state=state
    ):
        if candidate.is_file():
            return candidate
    return preferred_phase_artifact_path(
        root, phase_slug, status_filename, worktree=worktree, state=state
    )


def halt_dominant_tiebreak(
    candidates: list[tuple[Path, dict[str, Any]]],
) -> tuple[Path, dict[str, Any]] | None:
    """Binding halt wins over HEAD-match disambiguation (PRD 059 R6)."""
    halts = [
        (path, status)
        for path, status in candidates
        if status.get("verdict") == "halt" and status.get("binding")
    ]
    if not halts:
        return None
    halts.sort(
        key=lambda item: str(item[1].get("writtenAt") or item[1].get("updatedAt") or ""),
        reverse=True,
    )
    return halts[0]


# --- Resume blocker remediation (PRD 337 R15) ---------------------------------

CAUSE_RESUME_NONE = "resume:none"
CAUSE_AMBIGUOUS_RUN = "ambiguous-run"
CAUSE_DEAD_LEASE = "dead-lease"
CAUSE_TOKEN_SCOPE = "token-scope"

RESUME_BLOCKER_CAUSES = frozenset(
    {CAUSE_RESUME_NONE, CAUSE_AMBIGUOUS_RUN, CAUSE_DEAD_LEASE, CAUSE_TOKEN_SCOPE}
)


def redact_resume_blocker_context(value: Any) -> Any:
    """Redact credential material from resume blocker context (R15)."""
    from _sw.host._emit_redact import redact_emit_value

    return redact_emit_value(value)


def resume_command_for_blocker(
    cause: str,
    root: Path,
    *,
    run_id: str | None = None,
    task_list: str | None = None,
    lock_path: str | None = None,
    token_env: str | None = None,
    candidate_run_id: str | None = None,
) -> str:
    """One executable resume command without credential material (R15)."""
    root_str = str(root.resolve())
    if cause == CAUSE_AMBIGUOUS_RUN:
        if candidate_run_id:
            return (
                f"python3 scripts/wave_deliver.py {root_str} resume-locate "
                f"--run-id {candidate_run_id}"
            )
        return f"python3 scripts/wave_deliver.py {root_str} list"
    if cause == CAUSE_DEAD_LEASE:
        rid = (run_id or "unknown").strip() or "unknown"
        parts = [f"python3 scripts/wave_lock.py {root_str} run-lease acquire --run-id {rid}"]
        if task_list:
            parts.append(f"--task-list {task_list}")
        if lock_path:
            parts.append(f"# stale lock: {lock_path}")
        return " ".join(parts)
    if cause == CAUSE_TOKEN_SCOPE:
        if token_env:
            from credentials.checklist import CONFIGURE_CREDENTIAL_SELECTOR_ADD

            return (
                f"{CONFIGURE_CREDENTIAL_SELECTOR_ADD} --ref <ref> --backend environment "
                f"... --token-env {token_env!r}"
            )
        from credentials import failure_codes as fc
        from credentials.doctor import remediation_for_code

        return remediation_for_code(fc.INSUFFICIENT_SCOPE, root=root).command
    if cause == CAUSE_RESUME_NONE:
        return f"python3 scripts/wave_deliver.py {root_str} run --task-list <path>"
    return f"python3 scripts/wave_deliver.py {root_str} resume-locate"


def build_resume_blocker(
    cause: str,
    root: Path,
    *,
    context: dict[str, Any] | None = None,
    run_id: str | None = None,
    task_list: str | None = None,
    **command_kw: Any,
) -> dict[str, Any]:
    """Normalize a resume blocker: typed cause, redacted context, resume command (R15)."""
    ctx = redact_resume_blocker_context(context or {})
    cmd = resume_command_for_blocker(
        cause,
        root,
        run_id=run_id,
        task_list=task_list,
        **command_kw,
    )
    return {
        "verdict": "fail",
        "cause": cause,
        "context": ctx,
        "resumeCommand": cmd,
    }


def _find_dead_pid_run_lease(root: Path) -> dict[str, Any] | None:
    from wave_lock import (
        lock_host,
        read_lock_meta,
        run_lease_is_stale,
        run_lease_locks_dir,
        run_lease_ownership_certain,
        ship_lease_pid_alive,
    )

    locks_dir = run_lease_locks_dir(root)
    if not locks_dir.is_dir():
        return None
    for lock_file in sorted(locks_dir.glob("*.lock")):
        meta = read_lock_meta(lock_file)
        if not meta or meta.get("kind") != "deliver-run-lease":
            continue
        if meta.get("host") != lock_host():
            continue
        if not run_lease_ownership_certain(meta):
            continue
        if ship_lease_pid_alive(meta):
            continue
        if not run_lease_is_stale(meta):
            continue
        return {
            "runId": meta.get("runId"),
            "lockPath": str(lock_file),
            "holder": meta,
        }
    return None


def _detect_token_scope_blocker(
    root: Path,
    *,
    environ: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    import os

    from credentials.config_surface import resolve_config_surface
    from credentials.doctor import detect_undeclared_ambient_token_resolution

    cfg_path = root / ".cursor" / "workflow.config.json"
    if not cfg_path.is_file():
        return None
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(cfg, dict):
        return None
    try:
        surfaces = resolve_config_surface(cfg)
    except Exception:
        return None
    env = environ if environ is not None else dict(os.environ)
    for surface_name, surface in (
        ("host", surfaces.host),
        ("planning", surfaces.planning),
    ):
        detected = detect_undeclared_ambient_token_resolution(
            surface,
            root=root,
            environ=env,
        )
        if detected:
            token_env, _remediation = detected
            return {
                "surface": surface_name,
                "tokenEnv": token_env,
                "detail": "ambient token lacks environment-backend declaration",
            }
    return None


def classify_resume_blocker(
    root: Path,
    *,
    run_id: str | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Classify resume blockers with typed cause, redacted context, and resume command (R15)."""
    from wave_deliver import is_nonterminal_verdict, list_deliver_runs, locate_run

    dead = _find_dead_pid_run_lease(root)
    if dead:
        rid = str(dead.get("runId") or run_id or "")
        return build_resume_blocker(
            CAUSE_DEAD_LEASE,
            root,
            context=dead,
            run_id=rid,
            lock_path=str(dead.get("lockPath") or ""),
        )

    token_block = _detect_token_scope_blocker(root, environ=environ)
    if token_block:
        return build_resume_blocker(
            CAUSE_TOKEN_SCOPE,
            root,
            context=token_block,
            token_env=str(token_block.get("tokenEnv") or ""),
        )

    if run_id:
        located = locate_run(root, run_id)
        if located and is_nonterminal_verdict(located.get("terminalStatus")):
            return {
                "verdict": "pass",
                "cause": None,
                "runId": run_id,
                "taskList": located.get("taskList"),
            }

    candidates = [
        entry
        for entry in list_deliver_runs(root)
        if is_nonterminal_verdict(entry.get("terminalStatus"))
    ]
    if not candidates:
        return build_resume_blocker(CAUSE_RESUME_NONE, root, context={"runs": []})
    if len(candidates) > 1:
        run_ids = [str(entry.get("runId") or "") for entry in candidates]
        first_id = run_ids[0] if run_ids else None
        return build_resume_blocker(
            CAUSE_AMBIGUOUS_RUN,
            root,
            context={"runs": run_ids},
            candidate_run_id=first_id,
        )
    only = candidates[0]
    return {
        "verdict": "pass",
        "cause": None,
        "runId": only.get("runId"),
        "taskList": only.get("taskList"),
    }
