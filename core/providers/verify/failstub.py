#!/usr/bin/env python3
"""Fixture-only E2E adapter — emits failure JSON then exits non-zero."""
from __future__ import annotations
import json, os, sys
from pathlib import Path

def main() -> int:
    log = Path(os.environ.get("TMPDIR", "/tmp")) / "sw-verify.e2e.fail.log"
    log.write_text("stub e2e verify fail\n", encoding="utf-8")
    print(json.dumps({
        "status": "failed", "exitCode": 1, "name": "e2e", "provider": "failstub",
        "logPath": str(log), "skipped": False, "reason": "fixture failure",
    }))
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
