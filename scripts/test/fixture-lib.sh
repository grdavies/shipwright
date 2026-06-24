#!/usr/bin/env bash
# Shared helpers for scripts/test/*-fixtures.sh
# Content dirs (commands/, skills/, rules/, agents/) live under repo root or core/.
set -euo pipefail

if [[ -z "${ROOT:-}" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

# content_path <relative> — print absolute path; prefer root, then core/
content_path() {
  local rel="${1:?relative path e.g. commands/sw-prd.md}"
  if [[ -f "$ROOT/$rel" ]]; then
    printf '%s\n' "$ROOT/$rel"
  elif [[ -f "$ROOT/core/$rel" ]]; then
    printf '%s\n' "$ROOT/core/$rel"
  else
    printf '%s\n' "$ROOT/$rel"
    return 1
  fi
}
