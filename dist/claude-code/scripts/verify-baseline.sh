#!/usr/bin/env bash
# Opt-in baseline capture for verification-gate attribution (plan 005 U3).
#
# Usage:
#   verify-baseline.sh capture --from STATUS --to BASELINE [--gate-from PATH --gate-to PATH]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=evidence-read.sh
source "$ROOT/scripts/evidence-read.sh"

FROM=""
TO=""
GATE_FROM=""
GATE_TO=""

usage() {
  echo "Usage: verify-baseline.sh capture --from STATUS --to BASELINE [--gate-from PATH --gate-to PATH]" >&2
  exit 2
}

copy_baseline() {
  local src="$1" dst="$2"
  [[ -f "$src" ]] || { echo "source missing: $src" >&2; return 1; }
  if ! safe_jq "$src" '.' >/dev/null 2>&1; then
    echo "source invalid JSON: $src" >&2
    return 1
  fi
  local tmp
  tmp="$(mktemp "${dst}.XXXXXX")"
  chmod 600 "$tmp"
  safe_jq "$src" '.' >"$tmp"
  mv -f "$tmp" "$dst"
  chmod 600 "$dst"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    capture) shift ;;
    --from) FROM="${2:-}"; shift 2 ;;
    --to) TO="${2:-}"; shift 2 ;;
    --gate-from) GATE_FROM="${2:-}"; shift 2 ;;
    --gate-to) GATE_TO="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$FROM" && -n "$TO" ]] || usage

copy_baseline "$FROM" "$TO"

if [[ -n "$GATE_FROM" || -n "$GATE_TO" ]]; then
  [[ -n "$GATE_FROM" && -n "$GATE_TO" ]] || {
    echo "both --gate-from and --gate-to required together" >&2
    exit 2
  }
  copy_baseline "$GATE_FROM" "$GATE_TO"
fi
