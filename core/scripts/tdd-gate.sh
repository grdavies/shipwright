#!/usr/bin/env bash
# Per-task TDD red-green gate (IM5 / U7). Consumes structured /tmp/sw-tdd.status.json.
#
# Exit codes:
#   0  pass
#  10  skipped
#  20  fail
set -euo pipefail

STATUS_FILE=""

usage() {
  echo "Usage: tdd-gate.sh --status PATH" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --status) STATUS_FILE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$STATUS_FILE" ]] || usage
[[ -f "$STATUS_FILE" ]] || {
  jq -n --arg f "$STATUS_FILE" '{verdict:"fail",error:"status file missing",path:$f}'
  exit 20
}

exec python3 - "$STATUS_FILE" <<'PY'
import json, sys
from pathlib import Path

path = Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except json.JSONDecodeError:
    print(json.dumps({"verdict": "fail", "error": "invalid json"}))
    sys.exit(20)

if data.get("skipped"):
    reason = data.get("skipReason") or "no test scenario"
    print(json.dumps({"verdict": "skipped", "taskRef": data.get("taskRef"), "reason": reason}))
    sys.exit(10)

if data.get("testWeakened"):
    print(json.dumps({"verdict": "fail", "reason": "test weakened to force green", "taskRef": data.get("taskRef")}))
    sys.exit(20)

red = data.get("red") or {}
green = data.get("green") or {}
red_obs = bool(red.get("observed"))
green_obs = bool(green.get("observed"))
red_ec = red.get("exitCode")
green_ec = green.get("exitCode")

if not red_obs:
    print(json.dumps({"verdict": "fail", "reason": "red phase not observed", "taskRef": data.get("taskRef")}))
    sys.exit(20)

if red_ec == 0:
    print(json.dumps({"verdict": "fail", "reason": "red phase passed — test was already green", "taskRef": data.get("taskRef")}))
    sys.exit(20)

if not green_obs:
    print(json.dumps({"verdict": "fail", "reason": "green phase not observed", "taskRef": data.get("taskRef")}))
    sys.exit(20)

if green_ec != 0:
    print(json.dumps({"verdict": "fail", "reason": "green phase did not pass", "taskRef": data.get("taskRef")}))
    sys.exit(20)

print(json.dumps({
    "verdict": "pass",
    "taskRef": data.get("taskRef"),
    "rid": data.get("rid"),
    "testScenario": data.get("testScenario"),
}))
sys.exit(0)
PY
