#!/usr/bin/env python3
"""Explicit no-op E2E verify adapter."""
from __future__ import annotations
import json

def main() -> int:
    print(json.dumps({
        "status": "skipped", "exitCode": 0, "name": "e2e", "provider": "none",
        "logPath": "", "skipped": True, "reason": "verifyE2e.provider is none",
    }))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
