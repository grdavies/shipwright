#!/usr/bin/env bash
# Back-compat wrapper around dispatch-check for reviewer/persona/native-panel agents.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT/scripts/dispatch-check.sh" "$@"
