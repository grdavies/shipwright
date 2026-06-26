#!/usr/bin/env bash
# Shared at-entry nudge for stale config (PRD 018 R32) — closed surface set.
# Usage: config-at-entry.sh [--quiet]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

CONFIG=""
for candidate in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
  [[ -f "$candidate" ]] && CONFIG="$candidate" && break
done

[[ -x "$ROOT/scripts/sw-configure.sh" ]] || exit 0
OUT="$(bash "$ROOT/scripts/sw-configure.sh" drift-check --config "${CONFIG:-/nonexistent}" 2>/dev/null || echo '{}')"
STALE="$(echo "$OUT" | jq -r '.stale // false' 2>/dev/null || echo false)"
if [[ "$STALE" == "true" && "$QUIET" -eq 0 ]]; then
  echo "config may be stale; run /sw-init to refresh"
fi
