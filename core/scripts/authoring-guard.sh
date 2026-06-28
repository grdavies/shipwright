#!/usr/bin/env bash
# Authoring-guard preflight for unit-writing commands (PRD 032 R5/R6/R14).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "${PWD}" rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$REPO_ROOT" ]]; then
  REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi
exec python3 "$SCRIPT_DIR/authoring_guard.py" "$REPO_ROOT" "$@"
