#!/usr/bin/env python3
"""Host provider doctor — validate provider, token, remote (PRD 026 R33, R34)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="host-doctor.py")
    parser.add_argument("--root", default=None)
    args = parser.parse_args(argv)
    root = Path(args.root).resolve() if args.root else SCRIPT_DIR.parent
    host = root / "scripts" / "host_lib.py"
    resolved = json.loads(subprocess.check_output([sys.executable, str(host), "--root", str(root), "resolve"], text=True))
    token = json.loads(subprocess.check_output([sys.executable, str(host), "--root", str(root), "token-status"], text=True))
    warnings: list[str] = []
    checks: list[dict] = []
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
    verdict = "fail" if any(c.get("status") == "fail" for c in checks) else ("degraded" if warnings else "ok")
    print(json.dumps({
        "verdict": verdict,
        "provider": provider,
        "warnings": warnings,
        "checks": checks,
        "migration": {"githubTokenOnly": provider == "github" and token.get("present") and not resolved.get("configured")},
    }, indent=2))
    return 0


if __name__ == "__main__":
    run_module_main(main)
