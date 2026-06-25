#!/usr/bin/env bash
# Detect Cursor vs Claude Code for /sw-setup model catalog selection.
# Usage: detect-platform.sh [--json]
# Exit: 0 with platform id on stdout; 2 when ambiguous without SW_SETUP_PLATFORM override.
set -euo pipefail

if [[ -n "${SW_SETUP_PLATFORM:-}" ]]; then
  platform="$SW_SETUP_PLATFORM"
else
  if [[ -n "${CURSOR_AGENT:-}" || -n "${CURSOR_PLUGIN_ROOT:-}" ]]; then
    platform="cursor"
  elif [[ -n "${CLAUDE_CODE:-}" || -n "${CLAUDE_CODE_SSE_PORT:-}" || -n "${CLAUDE_PLUGIN_ROOT:-}" ]]; then
    platform="claude-code"
  else
  platform="cursor"
  fi
fi

case "$platform" in
  cursor|claude-code) ;;
  *)
    echo '{"verdict":"fail","error":"unknown platform"}' >&2
    exit 2
    ;;
esac

if [[ "${1:-}" == "--json" ]]; then
  printf '{"platform":"%s"}\n' "$platform"
else
  printf '%s\n' "$platform"
fi
