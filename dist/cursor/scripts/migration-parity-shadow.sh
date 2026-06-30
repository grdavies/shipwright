#!/usr/bin/env bash
# Dual-run shadow harness — legacy vs selector per migration family (PRD 021 TR9).
#
# Usage: migration-parity-shadow.py --family <doc-review|code-review|providers|dispatch> [--context PATH|JSON]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAMILY=""
CONTEXT_JSON="{}"

usage() {
  echo "Usage: migration-parity-shadow.py --family FAMILY [--context PATH] [--context-json JSON]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --family) FAMILY="${2:-}"; shift 2 ;;
    --context) CONTEXT_JSON="$(cat "${2:-}")"; shift 2 ;;
    --context-json) CONTEXT_JSON="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$FAMILY" ]] || usage

python3 - "$ROOT" "$FAMILY" "$CONTEXT_JSON" <<'PY'
import json, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1] + "/scripts")
from capability_migration_parity import dual_run

root = Path(sys.argv[1])
family = sys.argv[2]
ctx = json.loads(sys.argv[3] or "{}")
result = dual_run(family, ctx, repo_root=root, skip_freshness=False)
print(json.dumps(result, ensure_ascii=False, indent=2))
sys.exit(0 if result.get("match") else 1)
PY
