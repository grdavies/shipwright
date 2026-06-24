#!/usr/bin/env bash
# Fixture-friendly E2E verify adapter — always passes.
set -euo pipefail
LOG="${TMPDIR:-/tmp}/pf-verify.e2e.log"
echo "stub e2e verify ok" >"$LOG"
jq -n --arg log "$LOG" '{
  status: "complete",
  exitCode: 0,
  name: "e2e",
  provider: "stub",
  logPath: $log,
  skipped: false,
  reason: ""
}'
