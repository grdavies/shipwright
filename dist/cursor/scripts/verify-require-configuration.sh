#!/usr/bin/env bash
# Neutral verify.test sentinel for shipped example configs (PRD 018 R10).
# Fails until /sw-init writes real verify commands — not an echo-pass or fixture runner.
set -euo pipefail
echo "verify.test not configured — run /sw-init" >&2
exit 1
