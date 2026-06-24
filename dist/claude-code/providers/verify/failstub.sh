#!/usr/bin/env bash
# Fixture-only E2E adapter — emits failure JSON then exits non-zero (playwright failure shape).
set -euo pipefail
LOG="${TMPDIR:-/tmp}/sw-verify.e2e.fail.log"
echo "stub e2e verify fail" >"$LOG"
jq -n --arg log "$LOG" '{
  status: "failed",
  exitCode: 1,
  name: "e2e",
  provider: "failstub",
  logPath: $log,
  skipped: false,
  reason: "fixture failure"
}'
exit 1
