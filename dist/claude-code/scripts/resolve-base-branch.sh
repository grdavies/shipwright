#!/usr/bin/env bash
# Base-branch resolution CLI (PRD 018 TR4) — delegates to resolve_base_branch.py.
#
# Usage:
#   resolve-base-branch.py capture [--base BRANCH] [--force]
#   resolve-base-branch.py resolve [--base BRANCH] [--require-persisted] [--quiet] [--name-only]
#   resolve-base-branch.py disclose [--quiet]
#   resolve-base-branch.py diff-base [--base BRANCH] [--ci]
#   resolve-base-branch.py trunk-name
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/resolve_base_branch.py" "$@"
