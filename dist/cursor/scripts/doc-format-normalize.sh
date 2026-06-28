#!/usr/bin/env bash
# CLI wrapper for scripts/doc_format.py (PRD 031 R22).
# Phase 1: tokenize / emit / lint-callsites. Phase 2 adds --check / --write.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/doc_format.py" "$@"
