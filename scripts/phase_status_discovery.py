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
    # Slug-keyed artifacts coexist until run-scoped paths are populated (R20/R21).
    for legacy in _legacy_slug_candidate_paths(
        root, phase_slug, status_filename, worktree=wt, state=loaded
    ):
        if legacy not in paths:
            paths.append(legacy)
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
