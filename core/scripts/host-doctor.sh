#!/usr/bin/env bash
# Host provider doctor — validate provider, token, remote (PRD 026 R33, R34).
#
# Usage:
#   host-doctor.sh [--root PATH]
#
# Exit 0 always (warnings only); JSON verdict on stdout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --root) ROOT="$2"; shift 2 ;;
    -h|--help)
      sed -n '2,6p' "$0"
      exit 0
      ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

RESOLVED="$(python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" resolve)"
TOKEN="$(python3 "$ROOT/scripts/host_lib.py" --root "$ROOT" token-status)"

python3 - "$RESOLVED" "$TOKEN" <<'PY'
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
PY
