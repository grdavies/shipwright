#!/usr/bin/env python3
"""Drive Claude Code session hook adapter for fixture tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "core" / "hooks"))
sys.path.insert(0, str(ROOT / "platforms" / "claude-code"))

import hook_adapter  # noqa: E402


def main() -> int:
    workspace = sys.argv[1] if len(sys.argv) > 1 else str(ROOT)
    payload = {"cwd": workspace, "hook_event_name": "SessionStart"}
    return hook_adapter._run_session_with_payload(ROOT, payload)


if __name__ == "__main__":
    raise SystemExit(main())
