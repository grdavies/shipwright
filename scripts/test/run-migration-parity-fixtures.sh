#!/usr/bin/env bash
# Migration parity golden fixtures — dual-run shadow per family (PRD 021 R13, TR9).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SHADOW="$ROOT/scripts/migration-parity-shadow.sh"
FIX="$ROOT/scripts/test/fixtures/migration-parity"
FAIL=0

chmod +x "$SHADOW" "$ROOT/scripts/doc-review-select.sh" "$ROOT/scripts/code-review-select.sh"

run_family() {
  local name="$1" family="$2" ctx="$3"
  set +e
  OUT=$(bash "$SHADOW" --family "$family" --context-json "$ctx" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq 0 ]; then
    echo "OK  $name"
  else
    echo "FAIL $name"
    echo "$OUT"
    FAIL=1
  fi
}

# --- migration-parity-doc-review ---
run_family migration-parity-doc-review-core doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# Minimal PRD\nPlain requirements."}'
run_family migration-parity-doc-review-security doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# Auth PRD\nOAuth login and session handling."}'
run_family migration-parity-doc-review-design doc-review '{"version":1,"tier":"standard","phase_type":"sw-doc-review","body_snapshot":"# UI PRD\n## Screens\nCheckout wireframe."}'
run_family migration-parity-doc-review-quick doc-review '{"version":1,"tier":"quick","phase_type":"sw-doc-review","body_snapshot":"# Quick"}'

# --- migration-parity-code-review ---
for fixture in native-diff-minimal native-diff-selection native-diff-adversarial-50 native-diff-data-migration native-diff-reliability; do
  DIGEST=$(cat "$ROOT/scripts/test/fixtures/code-review/${fixture}.json")
  run_family "migration-parity-code-review-${fixture}" code-review "{\"version\":1,\"phase_type\":\"sw-review\",\"change_digest\":$DIGEST}"
done

# --- migration-parity-providers ---
CFG=$(python3 - <<'PY' "$ROOT/.cursor/workflow.config.json"
import json, sys
print(json.dumps({"version":1,"phase_type":"sw-ship","config":json.load(open(sys.argv[1]))}))
PY
)
run_family migration-parity-providers providers "$CFG"

# --- migration-parity-dispatch ---
run_family migration-parity-dispatch-inline dispatch '{"version":1,"file_paths":["a.ts","b.ts"],"conductor_mode":"inline"}'
run_family migration-parity-dispatch-delegate dispatch '{"version":1,"file_paths":["a.ts","b.ts","c.ts","d.ts"],"conductor_mode":"inline"}'
run_family migration-parity-dispatch-background dispatch '{"version":1,"file_paths":["a.ts"],"conductor_mode":"background_phase"}'

if [ "$FAIL" -eq 0 ]; then
  echo "ALL migration-parity fixtures passed"
else
  echo "SOME migration-parity fixtures FAILED"
  exit 1
fi
