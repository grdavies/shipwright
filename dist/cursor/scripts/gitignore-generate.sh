#!/usr/bin/env bash
# Visibility-driven .gitignore generator (PRD 034 R13).
# Usage: gitignore-generate.py [--repo-root ROOT] generate [--write] | verify-index
set -euo pipefail
PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$PLUGIN_ROOT"
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)
      REPO_ROOT="${2:-}"
      shift 2
      ;;
    *)
      ARGS+=("$1")
      shift
      ;;
  esac
done
export PYTHONPATH="${PLUGIN_ROOT}/scripts:${PYTHONPATH:-}"
exec python3 "${PLUGIN_ROOT}/scripts/gitignore_generate.py" --root "$REPO_ROOT" "${ARGS[@]}"
