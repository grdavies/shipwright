#!/usr/bin/env bash
# Feedback closure eligibility gate (IM8 / U9). Reuses verify status + optional gate JSON.
#
# Exit codes:
#   0  closable
#  10  inconclusive
#  20  not-closable
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKLOG=""
SIGNAL_ID=""
VERIFY_STATUS=""
GATE_JSON=""
REQUIRE_GATE=0

usage() {
  echo "Usage: feedback-closure-gate.py --backlog PATH --signal-id ID --verify-status PATH [--gate-json PATH --require-gate]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --backlog) BACKLOG="${2:-}"; shift 2 ;;
    --signal-id) SIGNAL_ID="${2:-}"; shift 2 ;;
    --verify-status) VERIFY_STATUS="${2:-}"; shift 2 ;;
    --gate-json) GATE_JSON="${2:-}"; shift 2 ;;
    --require-gate) REQUIRE_GATE=1; shift ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$BACKLOG" && -n "$SIGNAL_ID" && -n "$VERIFY_STATUS" ]] || usage

# shellcheck source=evidence-read.py
source "$ROOT/scripts/evidence-read.py"
if [[ ! -f "$VERIFY_STATUS" ]] || ! safe_read_check "$VERIFY_STATUS"; then
  jq -n --arg id "$SIGNAL_ID" '{verdict:"inconclusive",reason:"verify status missing or rejected by safe_read",signalId:$id}'
  exit 10
fi
if [[ "$REQUIRE_GATE" -eq 1 && -n "$GATE_JSON" ]]; then
  if [[ ! -f "$GATE_JSON" ]] || ! safe_read_check "$GATE_JSON"; then
    jq -n --arg id "$SIGNAL_ID" '{verdict:"inconclusive",reason:"gate json missing or rejected by safe_read",signalId:$id}'
    exit 10
  fi
fi

exec python3 - "$ROOT" "$BACKLOG" "$SIGNAL_ID" "$VERIFY_STATUS" "$GATE_JSON" "$REQUIRE_GATE" <<'PY'
import json, subprocess, sys
from pathlib import Path

root, backlog, signal_id, verify_status, gate_json, require_gate_s = sys.argv[1:7]
require_gate = require_gate_s == "1"

list_out = subprocess.check_output(
    ["bash", str(Path(root) / "scripts/feedback-backlog.py"), "list", "--open-only", "--backlog", backlog],
    text=True,
)
items = json.loads(list_out)
match = next((i for i in items if i.get("signalId") == signal_id), None)

if not match:
    print(json.dumps({"verdict": "not-closable", "reason": "signal not open in backlog", "signalId": signal_id}))
    sys.exit(20)

def verify_pass(path):
    p = Path(path)
    if not p.is_file():
        return "missing"
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return "invalid"
    ec = data.get("exitCode", data.get("overall", {}).get("exitCode", 1))
    st = data.get("status", data.get("overall", {}).get("status", "fail"))
    return "pass" if ec == 0 and st == "pass" else "fail"

def gate_pass(path):
    p = Path(path)
    if not p.is_file():
        return "missing"
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return "invalid"
    return "pass" if data.get("verdict") == "green" else "fail"

v = verify_pass(verify_status)
if v == "missing" or v == "invalid":
    print(json.dumps({"verdict": "inconclusive", "reason": "verify status missing or invalid", "signalId": signal_id}))
    sys.exit(10)
if v != "pass":
    print(json.dumps({"verdict": "not-closable", "reason": "verify not passing", "signalId": signal_id}))
    sys.exit(20)

if require_gate:
    g = gate_pass(gate_json)
    if g in ("missing", "invalid"):
        print(json.dumps({"verdict": "inconclusive", "reason": "gate json missing or invalid", "signalId": signal_id}))
        sys.exit(10)
    if g != "pass":
        print(json.dumps({"verdict": "not-closable", "reason": "gate not green", "signalId": signal_id}))
        sys.exit(20)

print(json.dumps({
    "verdict": "closable",
    "signalId": signal_id,
    "prNumber": match.get("prNumber"),
    "description": match.get("description"),
}))
sys.exit(0)
PY
