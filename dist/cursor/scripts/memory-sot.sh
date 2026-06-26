#!/usr/bin/env bash
# Provider-conditional source-of-truth resolver (PRD 015) — decision class only.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/memory_sot.py" "$@"
