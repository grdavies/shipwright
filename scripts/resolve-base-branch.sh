#!/usr/bin/env bash
# Base-branch resolution CLI (PRD 018 TR4) — delegates to resolve_base_branch.py.
#
# Usage:
#   resolve-base-branch.sh capture [--base BRANCH] [--force]
#   resolve-base-branch.sh resolve [--base BRANCH] [--require-persisted] [--quiet] [--name-only]
#   resolve-base-branch.sh disclose [--quiet]
#   resolve-base-branch.sh diff-base [--base BRANCH] [--ci]
#   resolve-base-branch.sh trunk-name
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/resolve_base_branch.py" "$@"
