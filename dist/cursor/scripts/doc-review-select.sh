#!/usr/bin/env bash
# Deterministic doc-review persona selection via capability selector (PRD 021 phase 6).
#
# Usage: doc-review-select.py [--context PATH] [--context-json JSON]
# Exit: 0; JSON stdout with panel + activation record shape
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONTEXT_JSON=""

usage() {
  echo "Usage: doc-review-select.py [--context PATH] [--context-json JSON]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --context)
      CONTEXT_JSON="$(cat "${2:-}")"
      shift 2
      ;;
    --context-json) CONTEXT_JSON="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

python3 - "$ROOT" "$CONTEXT_JSON" <<'PY'
import json, sys
from pathlib import Path

sys.path.insert(0, sys.argv[1] + "/scripts")
from capability_migration_parity import select_family

root = Path(sys.argv[1])
raw = sys.argv[2] or "{}"
ctx = json.loads(raw)
out = select_family("doc-review", ctx, repo_root=root, skip_freshness=False)
print(json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
PY
