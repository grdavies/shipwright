#!/usr/bin/env bash
# Playwright E2E verify adapter — runs when playwright config exists.
set -euo pipefail

ROOT="${PF_VERIFY_ROOT:-.}"
LOG="${TMPDIR:-/tmp}/sw-verify.e2e.log"
cd "$ROOT"

has_pw=false
for f in playwright.config.ts playwright.config.js playwright.config.mjs; do
  [[ -f "$f" ]] && has_pw=true && break
done

if ! $has_pw; then
  jq -n '{
    status: "skipped",
    exitCode: 0,
    name: "e2e",
    provider: "playwright",
    logPath: "",
    skipped: true,
    reason: "no playwright.config found"
  }'
  exit 0
fi

ROUTES="${PF_E2E_ROUTES:-[]}"
CMD=(npx playwright test)
FIRST_ROUTE="$(echo "$ROUTES" | jq -r '.[0] // empty' 2>/dev/null || true)"
if [[ -n "$FIRST_ROUTE" ]]; then
  CMD+=(--grep "$FIRST_ROUTE")
fi

set +e
"${CMD[@]}" >"$LOG" 2>&1
EC=$?
set -e

if [[ "$EC" -eq 0 ]]; then
  jq -n --arg log "$LOG" '{
    status: "complete",
    exitCode: 0,
    name: "e2e",
    provider: "playwright",
    logPath: $log,
    skipped: false,
    reason: ""
  }'
  exit 0
fi

jq -n --arg log "$LOG" --argjson ec "$EC" '{
  status: "failed",
  exitCode: $ec,
  name: "e2e",
  provider: "playwright",
  logPath: $log,
  skipped: false,
  reason: "playwright test failed"
}'
exit "$EC"
