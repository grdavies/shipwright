#!/usr/bin/env bash
# Explicit no-op E2E verify adapter.
set -euo pipefail
jq -n '{
  status: "skipped",
  exitCode: 0,
  name: "e2e",
  provider: "none",
  logPath: "",
  skipped: true,
  reason: "verifyE2e.provider is none"
}'
