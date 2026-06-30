#!/usr/bin/env bash
# Mechanical guard: refuse bare-branch filter-branch rewriting shared history (R42/R52).
set -euo pipefail

usage() {
  echo "usage: redaction-guard.py check-command -- <git args...>" >&2
  exit 2
}

check_filter_branch() {
  local joined="$*"
  if ! echo "$joined" | grep -qE 'filter-branch'; then
    return 0
  fi
  if echo "$joined" | grep -qE '\.\.'; then
    return 0
  fi
  echo "redaction-guard: refuse bare-branch filter-branch — use range-scoped redaction (base..branch)" >&2
  echo "See rules/sw-redaction-scope.mdc" >&2
  return 20
}

case "${1:-}" in
  check-command)
    shift
    [[ "${1:-}" == "--" ]] && shift
    check_filter_branch "$@"
    ;;
  *)
    usage
    ;;
esac
