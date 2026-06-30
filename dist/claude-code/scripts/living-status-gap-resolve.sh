#!/usr/bin/env bash
# Mechanical gap resolve on PRD ship (PRD 035 A2 R51).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || echo "$ROOT")"
absorbing=""; pr_ref=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --absorbing-prd) absorbing="${2:-}"; shift 2 ;;
    --pr) pr_ref="${2:-}"; shift 2 ;;
    *) echo '{"verdict":"fail","error":"unknown argument"}' >&2; exit 2 ;;
  esac
done
[[ -n "$absorbing" ]] || { echo '{"verdict":"fail","error":"--absorbing-prd required"}' >&2; exit 2; }
args=(flip --resolve --prd "$absorbing")
[[ -n "$pr_ref" ]] && args+=(--pr "$pr_ref")
exec python3 "$ROOT/scripts/gap_backlog.py" --root "$REPO_ROOT" "${args[@]}"
