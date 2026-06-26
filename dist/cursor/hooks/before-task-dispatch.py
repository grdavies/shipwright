#!/usr/bin/env python3
"""Thin Cursor entrypoint — delegates to core before_task_dispatch (PRD 012 R5)."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
import before_task_dispatch  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(before_task_dispatch.run_stdio())
