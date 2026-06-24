#!/usr/bin/env bash
# Assert full build chain regen: core/scripts sync, dist freshness, parity golden (R13).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
FAIL=0

if [[ -x "$ROOT/core/scripts/sw-assert-worktree.sh" ]]; then
  echo "OK  build-chain-regen: sw-assert-worktree synced to core/scripts"
else
  echo "FAIL build-chain-regen: core/scripts/sw-assert-worktree.sh missing"
  FAIL=1
fi

if [[ -x "$ROOT/scripts/check-frozen.sh" ]] && [[ ! -f "$ROOT/core/scripts/check-frozen.sh" ]]; then
  echo "OK  build-chain-regen: check-frozen harness at scripts/ root only (not emitted)"
else
  echo "FAIL build-chain-regen: check-frozen should be root harness only, not in core/scripts"
  FAIL=1
fi

bash "$ROOT/scripts/test/run-emitter-fixtures.sh" || FAIL=1
bash "$ROOT/scripts/test/run-parity-fixtures.sh" || FAIL=1

exit "$FAIL"
