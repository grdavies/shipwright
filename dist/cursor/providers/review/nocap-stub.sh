#!/usr/bin/env bash
# Gate-incompatible stub: declares no per-head-state capability.
set -euo pipefail
jq -n '{
  capabilities: { perHeadState: false },
  perHeadState: "in-flight",
  perHeadLanded: false,
  reviewedHead: null,
  statusContext: "absent",
  inProgressMarker: false,
  skipped: false,
  minutesSinceHeadPush: 0
}'
