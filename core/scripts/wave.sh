#!/usr/bin/env bash
# Wave plan + integration helpers (multi-feature + phase-mode).
# Usage:
#   wave.sh plan --task-list docs/prds/.../tasks-....md [--type feat] [--dry-run] [--from N]
#   wave.sh plan --items 'A,B,C' --edges 'C:A'
#   wave.sh preflight --task-list ... | --items ...
#   wave.sh integration --stamp <stamp> --branches 'branch1,branch2'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/wave_deliver.py" "$ROOT" "$@"
