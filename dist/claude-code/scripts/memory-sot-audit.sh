#!/usr/bin/env bash
# SoT-aware decision memory audit helpers (PRD 015 R9, R11).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/memory_sot_audit.py" "$@"
