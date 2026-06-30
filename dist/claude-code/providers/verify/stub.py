#!/usr/bin/env python3
"""Fixture-friendly E2E verify adapter — always passes."""
from __future__ import annotations
import json, os, sys
from pathlib import Path

def main() -> int:
    log = Path(os.environ.get("TMPDIR", "/tmp")) / "sw-verify.e2e.log"
    log.write_text("stub e2e verify ok\n", encoding="utf-8")
    print(json.dumps({
        "status": "complete", "exitCode": 0, "name": "e2e", "provider": "stub",
        "logPath": str(log), "skipped": False, "reason": "",
    }))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
