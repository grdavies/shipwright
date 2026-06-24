#!/usr/bin/env bash
# Per-run private temp dir for evidence files (plan 005 U4).
#
# Usage:
#   pf-tmp.sh init              Create 0700 run dir; record in phase-state; print path
#   pf-tmp.sh resolve           Print run dir ($PF_RUN_DIR → phase-state → empty)
#   pf-tmp.sh clean [max_age_s] Remove stale caller-owned pf-run.* dirs (default 86400)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PHASE_STATE="$ROOT/scripts/phase-state.sh"
# shellcheck source=evidence-read.sh
source "$ROOT/scripts/evidence-read.sh"
MAX_AGE="${2:-86400}"

caller_uid() {
  id -u
}

validate_tmp_parent() {
  local base="${TMPDIR:-/tmp}"
  [[ -d "$base" ]] || return 1
  [[ -L "$base" ]] && return 1
  return 0
}

cmd_init() {
  validate_tmp_parent || {
    echo '{"error":"invalid TMPDIR"}' >&2
    exit 2
  }
  local dir
  dir="$(mktemp -d "${TMPDIR:-/tmp}/pf-run.XXXXXX")"
  chmod 700 "$dir"
  validate_run_dir "$dir" || {
    rm -rf "$dir"
    echo '{"error":"invalid run dir"}' >&2
    exit 2
  }
  "$PHASE_STATE" write "$(jq -n --arg runDir "$dir" '{runDir: $runDir}')" >/dev/null
  printf '%s\n' "$dir"
}

cmd_resolve() {
  local dir=""
  if [[ -n "${PF_RUN_DIR:-}" ]]; then
    dir="$PF_RUN_DIR"
  else
    dir="$("$PHASE_STATE" read 2>/dev/null | jq -r '.runDir // empty' 2>/dev/null || true)"
  fi
  if [[ -n "$dir" && -d "$dir" ]]; then
    if validate_run_dir "$dir"; then
      printf '%s\n' "$dir"
    fi
  fi
  return 0
}

cmd_clean() {
  local base="${TMPDIR:-/tmp}" uid age now dir mtime
  uid="$(caller_uid)"
  age="${1:-86400}"
  now="$(date +%s)"
  shopt -s nullglob
  for dir in "$base"/pf-run.*; do
    [[ -d "$dir" ]] || continue
    [[ -L "$dir" ]] && continue
    local owner
    owner="$(stat -f '%u' "$dir" 2>/dev/null || stat -c '%u' "$dir")"
    [[ "$owner" == "$uid" ]] || continue
    mtime="$(stat -f '%m' "$dir" 2>/dev/null || stat -c '%Y' "$dir")"
    if [[ $((now - mtime)) -ge age ]]; then
      rm -rf "$dir"
    fi
  done
  shopt -u nullglob
}

CMD="${1:-}"
case "$CMD" in
  init) cmd_init ;;
  resolve) cmd_resolve ;;
  clean) cmd_clean "${2:-86400}" ;;
  -h|--help)
    echo "usage: pf-tmp.sh init|resolve|clean [max_age_seconds]"
    ;;
  *)
    echo "unknown command: $CMD" >&2
    exit 2
    ;;
esac
