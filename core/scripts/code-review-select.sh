#!/usr/bin/env bash
# Deterministic native panel roster selection from a diff (R7, R33, R47, R51, R61).
# Authoritative path: capability selector with legacy byte-parity (PRD 021 phase 6).
#
# Usage: code-review-select.sh --diff PATH|JSON [--diff-json INLINE]
# Exit: 0; JSON stdout with core, specialists, signals
set -euo pipefail

DIFF_INPUT=""
DIFF_INLINE=""

usage() {
  echo "Usage: code-review-select.sh --diff PATH|JSON [--diff-json INLINE]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --diff) DIFF_INPUT="${2:-}"; shift 2 ;;
    --diff-json) DIFF_INLINE="${2:-}"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "unknown arg: $1" >&2; usage ;;
  esac
done

[[ -n "$DIFF_INPUT" || -n "$DIFF_INLINE" ]] || usage

if [[ -n "$DIFF_INLINE" ]]; then
  DIFF_JSON="$DIFF_INLINE"
elif [[ -f "$DIFF_INPUT" ]]; then
  DIFF_JSON="$(cat "$DIFF_INPUT")"
else
  DIFF_JSON="$DIFF_INPUT"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export DIFF_JSON

python3 - "$ROOT" <<'PY'
import json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.join(sys.argv[1], "scripts"))
from capability_migration_parity import select_family

root = Path(sys.argv[1])
raw = os.environ.get("DIFF_JSON", "")
try:
    digest = json.loads(raw)
except json.JSONDecodeError:
    print(json.dumps({"error": "malformed diff JSON"}))
    sys.exit(1)

ctx = {"version": 1, "phase_type": "sw-review", "change_digest": digest}
out = select_family("code-review", ctx, repo_root=root, skip_freshness=False)
legacy_keys = ["core", "specialists", "signals", "executable_line_count", "adversarial_threshold", "excluded"]
payload = {k: out[k] for k in legacy_keys if k in out}
print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
PY
