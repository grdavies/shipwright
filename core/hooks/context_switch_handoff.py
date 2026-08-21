#!/usr/bin/env python3
"""Context-switch hook stub — dispatches HandoffBundle exporter on pause (PRD 280 R10)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from handoff_bundle import export_bundle  # noqa: E402


def export_on_context_switch(repo_root: Path, *, trigger: str = "context-switch") -> dict:
    """Read-only exporter invoked by harness pause hooks (Cursor ↔ Claude Code ↔ Codex)."""
    result = export_bundle(repo_root, handoff_degraded=False)
    payload = {
        "verdict": result.get("verdict"),
        "trigger": trigger,
        "readOnly": True,
        "resumeForbidden": True,
    }
    if result.get("verdict") == "pass" and isinstance(result.get("bundle"), dict):
        payload["bundleDigest"] = result["bundle"].get("bundleDigest")
        payload["phaseSlug"] = result["bundle"].get("phaseSlug")
    else:
        payload["error"] = result.get("error") or result.get("detail")
        payload["resumeCommand"] = result.get("resumeCommand")
    return payload


def main(argv: list[str] | None = None) -> int:
    repo_root = Path.cwd()
    trigger = "context-switch"
    args = list(argv or sys.argv[1:])
    if args and args[0] == "--trigger" and len(args) >= 2:
        trigger = args[1]
    payload = export_on_context_switch(repo_root, trigger=trigger)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(payload.get("verdict") or "")
    return 0 if verdict == "pass" else 20


if __name__ == "__main__":
    raise SystemExit(main())
