#!/usr/bin/env python3
"""Shared phase status discovery chain (PRD 059 R5/R6)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from status_integrity import resolve_status_candidates
from wave_json_io import StateCorruptError, read_json

TiebreakFn = Callable[[list[tuple[Path, dict[str, Any]]]], tuple[Path, dict[str, Any]] | None]


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


def glob_phase_status_paths(root: Path, phase_slug: str, status_filename: str) -> list[Path]:
    wt_root = root / ".sw-worktrees"
    if not wt_root.is_dir():
        return []
    return sorted(wt_root.glob(f"*/.cursor/sw-deliver-runs/{phase_slug}/{status_filename}"))


def collect_status_candidate_paths(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None = None,
) -> list[Path]:
    """Discovery chain: canonical → worktree-local → glob (PRD 059 R5)."""
    paths: list[Path] = []
    canonical = root / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename
    paths.append(canonical)
    if worktree is not None:
        paths.append(worktree / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename)
    paths.extend(glob_phase_status_paths(root, phase_slug, status_filename))
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
) -> tuple[Path | None, dict[str, Any] | None]:
    candidates = load_status_candidates(
        collect_status_candidate_paths(root, phase_slug, status_filename, worktree=worktree)
    )
    if not candidates:
        return None, None
    if tiebreak is not None:
        picked = tiebreak(candidates)
        if picked is not None:
            return picked
    return resolve_status_candidates(candidates, expected_head)


def first_existing_status_path(
    root: Path,
    phase_slug: str,
    status_filename: str,
    *,
    worktree: Path | None = None,
) -> Path:
    """Return the preferred on-disk path for a phase status artifact."""
    canonical = root / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename
    if worktree is not None:
        wt_path = worktree / ".cursor" / "sw-deliver-runs" / phase_slug / status_filename
        if wt_path.is_file():
            return wt_path
    if canonical.is_file():
        return canonical
    for candidate in glob_phase_status_paths(root, phase_slug, status_filename):
        if candidate.is_file():
            return candidate
    if worktree is not None:
        return wt_path
    return canonical


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
