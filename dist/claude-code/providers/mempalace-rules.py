#!/usr/bin/env python3
"""MemPalace out-of-band rule-fetcher for hooks (PRD 074).

Emits JSON rules to stdout. Agent-session ops use MemPalace MCP; this script is the
hook transport only (catalog ``hookTransport.ruleFetch: out-of-band-script``).

Phase-4 stub: non-applicable unless ``memory.provider == mempalace`` and the script
compiles for ``memory_provider_register`` / checklist reachability. Full room filter,
fixed-argv palacePath, cache integrity, and size caps land in the rules-script phases
(R19–R23).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def load_provider(root: Path) -> str:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            break
        memory = data.get("memory") or {}
        return str(memory.get("provider") or "").strip()
    return ""


def main() -> int:
    root = Path(os.environ.get("SW_WORKSPACE_ROOT") or Path.cwd())
    provider = load_provider(root)
    if provider != "mempalace":
        print(
            json.dumps(
                {
                    "ok": False,
                    "applicable": False,
                    "error": "non-applicable: memory.provider is not mempalace",
                    "provider": provider or None,
                    "rules": [],
                }
            )
        )
        return 0
    # Full palace enumeration is implemented in the rules-script phases (R19–R23).
    print(
        json.dumps(
            {
                "ok": True,
                "applicable": True,
                "provider": "mempalace",
                "rules": [],
                "notice": "mempalace-rules stub — configure palacePath and complete R19–R23 fetch",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
