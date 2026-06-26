#!/usr/bin/env bash
# Redacted decision snapshot writer for freeze path (PRD 015 R4–R6). Offline-safe — no provider calls.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/memory_decision_snapshot.py" "$@"
