#!/usr/bin/env bash
# Build-chain SoT fixtures (PRD 038 phase 1 — R3, R12).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- build-chain-sot-lint (R12) ---
if bash "$ROOT/scripts/build-chain-sot-lint.sh" >/dev/null 2>&1; then
  ok "build-chain-sot-lint"
else
  bad "build-chain-sot-lint"
fi

# --- copy-to-core-orphan-fail-closed (R3) ---
TMP_ORPHAN="$ROOT/core/sw-reference/.fixture-orphan-sot.json"
trap 'rm -f "$TMP_ORPHAN"' EXIT

touch "$TMP_ORPHAN"
if bash "$ROOT/scripts/copy-to-core.sh" >/dev/null 2>&1; then
  bad "copy-to-core-orphan-fail-closed: expected non-zero exit on orphan"
else
  ok "copy-to-core-orphan-fail-closed"
fi
rm -f "$TMP_ORPHAN"

# --- copy-to-core-orphan-force (R16) ---
touch "$TMP_ORPHAN"
if bash "$ROOT/scripts/copy-to-core.sh" --force >/dev/null 2>&1; then
  ok "copy-to-core-orphan-force"
else
  bad "copy-to-core-orphan-force"
fi
rm -f "$TMP_ORPHAN"

# --- copy-to-core-manifest-driven (R4/R13) ---
if bash "$ROOT/scripts/copy-to-core.sh" >/dev/null 2>&1; then
  ok "copy-to-core-manifest-driven"
else
  bad "copy-to-core-manifest-driven"
fi


# --- ci-yml-includes-core-scripts-parity (R5) ---
if grep -q 'run-core-scripts-parity-fixtures.sh' "$ROOT/.github/workflows/ci.yml"; then
  ok "ci-yml-includes-core-scripts-parity"
else
  bad "ci-yml-includes-core-scripts-parity"
fi

# --- verify-test-registers-core-scripts-parity (R6) ---
if python3 -c "
import json
m=json.load(open('$ROOT/core/sw-reference/pr-test-plan.manifest.json'))
ids=[f['id'] for f in m.get('fixtures',[])]
assert 'core-scripts-parity-fixtures' in ids
match=[f for f in m['fixtures'] if f['id']=='core-scripts-parity-fixtures'][0]
assert match['script']=='scripts/test/run-core-scripts-parity-fixtures.sh'
"; then
  ok "verify-test-registers-core-scripts-parity"
else
  bad "verify-test-registers-core-scripts-parity"
fi

exit "$FAIL"
