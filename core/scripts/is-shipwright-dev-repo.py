#!/usr/bin/env python3
"""Authoritative plugin-self vs consumer repository detection (PRD 338 R24)."""
from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from _sw.cli import run_module_main

DEV_SENTINEL = ".shipwright-dev"
HEURISTIC_MARKERS: tuple[tuple[str, str], ...] = (
    ("version.txt", "file"),
    ("core/sw-reference", "dir"),
    ("scripts/check-gate.py", "file"),
)
POSTURE_PLUGIN_SELF = "plugin-self"
POSTURE_CONSUMER = "consumer"


class SelfRepoDetectionError(ValueError):
    """Ambiguous or invalid repository layout for posture detection."""


@dataclass(frozen=True, slots=True)
class SelfRepoVerdict:
    posture: str
    sentinel_present: bool
    heuristic_markers_present: bool
    reason: str


def _marker_present(root: Path, relative: str, kind: str) -> bool:
    path = root / relative
    if kind == "file":
        return path.is_file()
    return path.is_dir()


def heuristic_markers_present(root: Path) -> bool:
    return all(_marker_present(root, relative, kind) for relative, kind in HEURISTIC_MARKERS)


def sentinel_present(root: Path) -> bool:
    return (root / DEV_SENTINEL).is_file()


def detect_self_repo(root: Path | str) -> SelfRepoVerdict:
    """Return unified plugin-self vs consumer posture for a repository root."""
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise SelfRepoDetectionError(f"repository root is not a directory: {resolved}")

    has_sentinel = sentinel_present(resolved)
    has_heuristics = heuristic_markers_present(resolved)

    if has_sentinel and not has_heuristics:
        raise SelfRepoDetectionError(
            "ambiguous layout: .shipwright-dev sentinel without expected dev-repo markers"
        )
    if has_sentinel and has_heuristics:
        return SelfRepoVerdict(
            posture=POSTURE_PLUGIN_SELF,
            sentinel_present=True,
            heuristic_markers_present=True,
            reason="sentinel-authoritative",
        )
    if has_heuristics and not has_sentinel:
        return SelfRepoVerdict(
            posture=POSTURE_CONSUMER,
            sentinel_present=False,
            heuristic_markers_present=True,
            reason="heuristic-markers-without-sentinel",
        )
    return SelfRepoVerdict(
        posture=POSTURE_CONSUMER,
        sentinel_present=False,
        heuristic_markers_present=False,
        reason="consumer",
    )


def is_shipwright_dev_repo(root: Path | str) -> bool:
    """True only when the authoritative sentinel confirms plugin-self posture."""
    try:
        verdict = detect_self_repo(root)
    except SelfRepoDetectionError:
        return False
    return verdict.posture == POSTURE_PLUGIN_SELF


def resolve_repo_root(argv: list[str]) -> Path:
    if argv:
        return Path(argv[0])
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path.cwd()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    return 0 if is_shipwright_dev_repo(resolve_repo_root(args)) else 1


if __name__ == "__main__":
    run_module_main(main)
