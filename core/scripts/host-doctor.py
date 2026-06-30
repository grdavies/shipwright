#!/usr/bin/env python3
"""Host provider doctor — validate provider, token, remote (PRD 026 R33, R34). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, sys

    resolved = json.loads(sys.argv[1])
    token = json.loads(sys.argv[2])
    warnings = []
    checks = []

    provider = resolved.get("provider", "none")
    checks.append({"check": "provider", "status": "ok" if resolved.get("verdict") == "ok" else "fail", "provider": provider})

    if resolved.get("verdict") != "ok":
        warnings.append(resolved.get("error", "unknown_provider"))

    remote = resolved.get("remote", "origin")
    remote_url = resolved.get("remoteUrl")
    if remote_url:
        checks.append({"check": "remote", "status": "ok", "remote": remote, "url": remote_url})
    else:
        checks.append({"check": "remote", "status": "warn", "remote": remote, "message": "remote not configured or missing"})
        warnings.append("missing-remote")

    if provider != "none":
        if token.get("present"):
            checks.append({"check": "token", "status": "ok", "tokenEnv": token.get("tokenEnv")})
        else:
            checks.append({"check": "token", "status": "degraded", "tokenEnv": token.get("tokenEnv")})
            warnings.append("missing-token")
    else:
        checks.append({"check": "token", "status": "skipped", "reason": "local-mode"})

    rate = resolved.get("rateLimit") or {}
    checks.append({"check": "rateLimit", "status": "ok", "config": rate})

    verdict = "ok"
    if any(c.get("status") == "fail" for c in checks):
        verdict = "fail"
    elif warnings:
        verdict = "degraded"

    print(json.dumps({
        "verdict": verdict,
        "provider": provider,
        "warnings": warnings,
        "checks": checks,
        "migration": {
            "githubTokenOnly": provider == "github" and token.get("present") and not resolved.get("configured"),
        },
    }, indent=2))
    return 0

if __name__ == "__main__":
    run_module_main(main)
