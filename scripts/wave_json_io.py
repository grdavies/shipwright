#!/usr/bin/env python3
"""Crash-safe JSON persistence shared by wave_state.py and wave_merge.py (PRD 007 R43)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class StateCorruptError(Exception):
    """Raised when a state file exists but is unreadable or not a JSON object."""


def read_json(path: Path, *, absent_ok: bool = True) -> dict[str, Any]:
    """Read a JSON object file.

    Missing file → ``{}`` when *absent_ok* (no run yet).
    Truncated/invalid JSON or non-object root → :class:`StateCorruptError` (never silent ``{}``).
    """
    if not path.is_file():
        if absent_ok:
            return {}
        raise StateCorruptError(f"state file missing: {path}")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise StateCorruptError(f"cannot read {path}: {exc}") from exc
    if not raw.strip():
        raise StateCorruptError(f"state file empty: {path}")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise StateCorruptError(f"state file corrupt: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise StateCorruptError(f"state file root must be object: {path}")
    return data


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomic write: temp file + fsync + rename (PRD 007 R43)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    try:
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass
    os.chmod(path, 0o600)
