#!/usr/bin/env python3
"""Deterministic native panel roster selection from a diff (R7, R33, R47, R51, R61). Authoritative path: capability selector with legacy byte-parity (PRD 021 phase 6)."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, os, sys
    from pathlib import Path

    sys.path.insert(0, os.path.join(sys.argv[1], "scripts"))
    from capability_migration_parity import select_family

    root = Path(sys.argv[1])
    raw = os.environ.get("DIFF_JSON", "")
    try:
        digest = json.loads(raw)
    except json.JSONDecodeError:
        print(json.dumps({"error": "malformed diff JSON"}))
        sys.exit(1)

    ctx = {"version": 1, "phase_type": "sw-review", "change_digest": digest}
    out = select_family("code-review", ctx, repo_root=root, skip_freshness=False)
    legacy_keys = ["core", "specialists", "signals", "executable_line_count", "adversarial_threshold", "excluded"]
    payload = {k: out[k] for k in legacy_keys if k in out}
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
    return 0

if __name__ == "__main__":
    run_module_main(main)
