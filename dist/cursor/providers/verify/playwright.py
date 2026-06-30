#!/usr/bin/env python3
"""Playwright E2E verify adapter — runs when playwright config exists."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path

def main() -> int:
    root = Path(os.environ.get("SW_VERIFY_ROOT", "."))
    log = Path(os.environ.get("TMPDIR", "/tmp")) / "sw-verify.e2e.log"
    configs = ("playwright.config.ts", "playwright.config.js", "playwright.config.mjs")
    if not any((root / f).is_file() for f in configs):
        print(json.dumps({
            "status": "skipped", "exitCode": 0, "name": "e2e", "provider": "playwright",
            "logPath": "", "skipped": True, "reason": "no playwright.config found",
        }))
        return 0
    routes_raw = os.environ.get("SW_E2E_ROUTES", "[]")
    try:
        routes = json.loads(routes_raw)
    except json.JSONDecodeError:
        routes = []
    cmd = ["npx", "playwright", "test"]
    if isinstance(routes, list) and routes:
        cmd.extend(["--grep", str(routes[0])])
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    log.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    if proc.returncode == 0:
        print(json.dumps({
            "status": "complete", "exitCode": 0, "name": "e2e", "provider": "playwright",
            "logPath": str(log), "skipped": False, "reason": "",
        }))
        return 0
    print(json.dumps({
        "status": "failed", "exitCode": proc.returncode, "name": "e2e", "provider": "playwright",
        "logPath": str(log), "skipped": False, "reason": "playwright test failed",
    }))
    return proc.returncode

if __name__ == "__main__":
    raise SystemExit(main())
