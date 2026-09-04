#!/usr/bin/env python3
"""PRD 081 R20/R21 — enumerated release-guide artifact currency bindings."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

# Sole authority for which operator guides must stay current with harness code (R21).
RELEASE_GUIDE_ARTIFACTS: tuple[dict[str, Any], ...] = (
    {
        "id": "layout",
        "doc": ".shipwright/layout.md",
        "sources": (
            "scripts/wave_run_paths.py",
            "scripts/doc_loop.py",
            "scripts/wave_lock.py",
            "scripts/wave_state.py",
        ),
        "markers": (
            "Per-run deliver layout",
            "Doc-run layout",
            "target-lock",
            "run-local lease",
        ),
    },
    {
        "id": "commands-guide",
        "doc": "docs/guides/commands.md",
        "sources": (
            "scripts/wave_deliver.py",
            "scripts/wave_terminal.py",
            "scripts/wave_run_adopt.py",
        ),
        "markers": (
            "Deliver operator surface",
            "resume-locate",
            "requiresAdoption",
            "run-finalize",
        ),
    },
    {
        "id": "workflows-guide",
        "doc": "docs/guides/workflows.md",
        "sources": (
            "scripts/planning_reserve.py",
            "scripts/doc_rescore.py",
            "scripts/doc_loop.py",
        ),
        "markers": (
            "Number reservation transaction",
            "Pre-freeze rescore",
            "Publication sequencing invariants",
        ),
    },
)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _git_last_commit_epoch(root: Path, rel_path: str) -> float | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%ct", "--", rel_path],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    line = proc.stdout.strip()
    return float(line) if line.isdigit() else None


def _content_age(root: Path, path: Path) -> float:
    """Prefer last git commit time so CI mtime noise does not false-positive stale guides."""
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return _mtime(path)
    git_age = _git_last_commit_epoch(root, rel)
    if git_age is not None:
        return git_age
    return _mtime(path)


def check_release_guide_artifacts(root: Path) -> list[dict[str, Any]]:
    """Return drift rows when a listed guide is missing, marker-incomplete, or stale."""
    drift: list[dict[str, Any]] = []
    for binding in RELEASE_GUIDE_ARTIFACTS:
        doc_rel = str(binding["doc"])
        doc_path = root / doc_rel
        if not doc_path.is_file():
            drift.append({"kind": "guide-missing", "artifact": doc_rel, "id": binding["id"]})
            continue

        text = doc_path.read_text(encoding="utf-8")
        missing_markers = [m for m in binding["markers"] if m not in text]
        if missing_markers:
            drift.append(
                {
                    "kind": "guide-marker-missing",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "missingMarkers": missing_markers,
                }
            )

        source_paths = [root / rel for rel in binding["sources"] if (root / rel).is_file()]
        if not source_paths:
            drift.append(
                {
                    "kind": "guide-sources-missing",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "sources": list(binding["sources"]),
                }
            )
            continue

        doc_mtime = _content_age(root, doc_path)
        newest_source = max(source_paths, key=lambda p: _content_age(root, p))
        newest_mtime = _content_age(root, newest_source)
        if doc_mtime + 1e-6 < newest_mtime:
            drift.append(
                {
                    "kind": "guide-stale",
                    "artifact": doc_rel,
                    "id": binding["id"],
                    "docMtime": doc_mtime,
                    "newestSource": newest_source.relative_to(root).as_posix(),
                    "sourceMtime": newest_mtime,
                }
            )
    return drift
