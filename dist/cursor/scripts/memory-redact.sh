#!/usr/bin/env bash
# Deterministic R41 redaction chokepoint — stdin or file arg → stdout (redacted).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$ROOT/memory_redact.py" "$@"
