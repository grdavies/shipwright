#!/usr/bin/env bash
# Placeholder taxonomy for verify.* commands (PRD 018 R3/R28).
#
# Usage: verify-unconfigured.py [--config PATH] [--json]
# Exit 0 when configured; 1 when unconfigured; 2 on error.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG=""
JSON=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --json) JSON=1; shift ;;
    -h|--help)
      echo "usage: verify-unconfigured.py [--config PATH] [--json]"
      exit 0
      ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$CONFIG" ]]; then
  for candidate in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
    if [[ -f "$candidate" ]]; then
      CONFIG="$candidate"
      break
    fi
  done
fi

exec python3 - "$CONFIG" "$JSON" <<'PY'
import json
import re
import sys
from pathlib import Path

config_path = sys.argv[1]
as_json = sys.argv[2] == "1"

VACUOUS = re.compile(
    r"^\s*(?:"
    r"|:\s*"
    r"|true\s*"
    r"|exit\s+0\s*"
    r"|echo\b.*"
    r")\s*$",
    re.I,
)


def is_vacuous(cmd: str) -> bool:
    if cmd is None:
        return True
    s = str(cmd).strip()
    if not s:
        return True
    if VACUOUS.match(s):
        return True
    return False


cfg = {}
if config_path and Path(config_path).is_file():
    cfg = json.loads(Path(config_path).read_text(encoding="utf-8"))

verify = cfg.get("verify") or {}
allow = bool(verify.get("allowUnconfigured", False))

unconfigured_keys = []
for key, cmd in verify.items():
    if key == "allowUnconfigured":
        continue
    if is_vacuous(cmd):
        unconfigured_keys.append(key)

configured = len(unconfigured_keys) == 0 and len(verify) > 0
if not verify:
    configured = False
    unconfigured_keys = ["all"]

finding = {
    "signal": "verify-unconfigured" if not configured else None,
    "configured": configured,
    "unconfiguredKeys": unconfigured_keys,
    "allowUnconfigured": allow,
    "cta": "run /sw-init",
    "blocking": not allow,
}

if as_json:
    print(json.dumps(finding, indent=2))
else:
    if configured:
        print("verify: configured")
    else:
        print(f"verify-unconfigured: {', '.join(unconfigured_keys)} — run /sw-init")

sys.exit(0 if configured or allow else 1)
PY
