#!/usr/bin/env bash
# Workflow push wrapper — secret scan before every git push (R50).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$(git rev-parse --show-toplevel)"
bash "$ROOT/secret-scan.sh" pre-push
exec git push "$@"
