#!/usr/bin/env python3
"""Thin Cursor entrypoint — context-switch HandoffBundle export (PRD 333 R3)."""
from __future__ import annotations
import sys
from pathlib import Path
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "core" / "hooks"))
import context_switch_handoff  # noqa: E402
if __name__ == "__main__":
    raise SystemExit(context_switch_handoff.main())
