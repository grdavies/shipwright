#!/usr/bin/env bash
# Author-time capability manifest lint — precedence conflicts and anti-spoof (R11, R25, R27).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$ROOT/scripts/capability_manifest_lint.py" --root "$ROOT" "$@"
