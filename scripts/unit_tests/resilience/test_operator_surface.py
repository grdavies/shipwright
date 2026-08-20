#!/usr/bin/env python3
"""Operator surface guard — no new sw-graph-* or parallel debug slash commands (PRD 323 R25)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_COMMAND_DIRS = [
    _REPO / "core" / "commands",
    _REPO / "commands",
    _REPO / "dist" / "cursor" / "commands",
    _REPO / "dist" / "claude-code" / "commands",
]

_FORBIDDEN = re.compile(r"^sw-graph-", re.IGNORECASE)
_PARALLEL_DEBUG = re.compile(r"^sw-debug-(graph|scheduler|workflow)-", re.IGNORECASE)


def _command_names() -> list[str]:
    names: list[str] = []
    for directory in _COMMAND_DIRS:
        if not directory.is_dir():
            continue
        for path in directory.glob("sw-*.md"):
            names.append(path.stem)
    return sorted(set(names))


def test_no_sw_graph_slash_commands() -> None:
    offenders = [name for name in _command_names() if _FORBIDDEN.search(name)]
    assert offenders == [], f"forbidden sw-graph-* commands: {offenders}"


def test_no_parallel_debug_scheduler_commands() -> None:
    offenders = [name for name in _command_names() if _PARALLEL_DEBUG.search(name)]
    assert offenders == [], f"forbidden parallel debug commands: {offenders}"


def test_existing_debug_surface_remains_sw_debug() -> None:
    names = set(_command_names())
    # Canonical debug entry must remain the unprefixed family root
    assert "sw-debug" in names or any(n.startswith("sw-debug") for n in names)
