#!/usr/bin/env python3
"""Thin Cursor entrypoint — delegates to platforms/cursor/hook_adapter."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
sys.path.insert(0, str(_REPO / "platforms" / "cursor"))

import hook_adapter  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(hook_adapter.run_session_start(_REPO))
