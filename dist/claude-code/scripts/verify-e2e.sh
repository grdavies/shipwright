#!/usr/bin/env bash
# E2E/smoke verify adapter selector (IM9 / U10). Modelled on check-gate review adapter seam.
#
# Usage: verify-e2e.sh [--config PATH]
# Prints adapter JSON to stdout; exit code mirrors adapter exitCode (skipped → 0).
set -euo pipefail

# shellcheck source=pf-resolve-plugin-root.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/pf-resolve-plugin-root.sh"
PLUGIN_ROOT="$(pf_resolve_plugin_root "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")"
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
CONFIG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="${2:-}"; shift 2 ;;
    -h|--help)
      echo "usage: verify-e2e.sh [--config PATH]" >&2
      exit 0
      ;;
    *) echo '{"status":"failed","reason":"unknown argument"}' >&2; exit 2 ;;
  esac
done

if [[ -z "$CONFIG" ]]; then
  for p in "$ROOT/.cursor/workflow.config.json" "$ROOT/workflow.config.json"; do
    [[ -f "$p" ]] && CONFIG="$p" && break
  done
fi

cfg() {
  if [[ -n "$CONFIG" && -f "$CONFIG" ]]; then
    jq -r "$1 // \"$2\"" "$CONFIG" 2>/dev/null || echo "$2"
  else
    echo "$2"
  fi
}

PROVIDER="$(cfg '.verifyE2e.provider' 'none')"
ENABLED="$(cfg '.verifyE2e.enabled' 'false')"

if [[ "$PROVIDER" == "none" || "$ENABLED" != "true" ]]; then
  exec bash "$PLUGIN_ROOT/providers/verify/none.sh"
fi

case "$PROVIDER" in
  [a-z0-9-]*) ;;
  *)
    jq -n --arg p "$PROVIDER" '{status:"failed",exitCode:2,name:"e2e",provider:$p,skipped:false,reason:"invalid provider id"}'
    exit 2
    ;;
esac

ADAPTER="$PLUGIN_ROOT/providers/verify/${PROVIDER}.sh"
if [[ ! -f "$ADAPTER" ]]; then
  jq -n --arg p "$PROVIDER" '{status:"failed",exitCode:2,name:"e2e",provider:$p,skipped:false,reason:"unknown verify provider"}'
  exit 2
fi

CHANGED="$( {
  git -C "$ROOT" diff --name-only 2>/dev/null || true
  git -C "$ROOT" diff --cached --name-only 2>/dev/null || true
  git -C "$ROOT" ls-files --others --exclude-standard 2>/dev/null || true
} | sort -u | paste -sd ',' - )"

export PF_VERIFY_ROOT="$ROOT"
export PF_CHANGED_FILES="${CHANGED//,/$'\n'}"
export PF_E2E_ROUTES="$(cfg '.verifyE2e.routes' '[]')"
export PF_E2E_CONFIG="${CONFIG:-}"

set +e
OUT="$(bash "$ADAPTER")"
ADAPTER_EC=$?
set -e
echo "$OUT"
EC="$(echo "$OUT" | jq -r '.exitCode // empty')"
if [[ -z "$EC" || "$EC" == "null" ]]; then
  EC="${ADAPTER_EC:-1}"
fi
exit "$EC"
