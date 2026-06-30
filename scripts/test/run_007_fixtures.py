#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
    src = _patch_source(_SOURCE, root)
    completed = subprocess.run(
        ["bash", "-c", src],
        cwd=str(root),
        env=env,
        shell=False,
    )
    return completed.returncode


_SOURCE = r"""
#!/usr/bin/env bash
# PRD 007 Testing Strategy table — aggregate fixture runner (R36).
# Verifies every named scenario is implemented and delegates to phase fixture scripts.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ALL_OUT=""
run_suite() {
  local script="$1"
  local out
  if out=$(bash "$ROOT/scripts/test/$script" 2>&1); then
    echo "SUITE PASS $script"
    echo "$out"
    ALL_OUT+="$out"$'\n'
  else
    echo "SUITE FAIL $script"
    echo "$out"
    ALL_OUT+="$out"$'\n'
    FAIL=1
  fi
}

# Phase / domain fixture suites
for suite in \
  run-branch-guard-fixtures.sh \
  run-state-fixtures.sh \
  run-deliver-loop-fixtures.sh \
  run-orchestrator-fixtures.sh \
  run-merge-queue-fixtures.sh \
  run-ship-phase-fixtures.sh \
  run-tasks-currency-fixtures.sh \
  run-secret-scan-fixtures.sh \
  run-cleanup-fixtures.sh \
  run-compound-completion-fixtures.sh \
  run-007-docs-fixtures.sh \
  run-emitter-fixtures.sh
do
  run_suite "$suite"
done

# PRD 007 Testing Strategy — every fixture name must appear in suite output
FIXTURES=(
  deliver-loop-resume-from-state
  deliver-loop-no-manual-handoff
  deliver-spec-seed-feature-branch
  deliver-advance-from-status-only
  deliver-blocker-clean-halt
  deliver-remediation-maxattempts-default
  tasks-checkbox-currency
  tasks-progress-nonckbox-reject
  tasks-currency-gate-block
  compound-ship-premerge-commit
  compound-ship-rule-class-gated
  branch-name-guard-floor
  branch-name-guard-multifeature
  branch-name-guard-creation
  pf-matcher-migration
  cleanup-dry-run-default
  cleanup-protects-inflight
  deliver-suggest-cleanup-on-merge
  cleanup-registered
  emitter-freshness-007
  status-collect-phase-path
  merge-run-next-no-pr
  primary-ref-autosync
  secret-scan-prepush
  redaction-range-scoped-guard
  state-write-atomic-crash
  lock-stale-reclaim
  merge-journal-idempotent-replay
  driver-heartbeat-timeout-halt
  status-sha-freshness
  frozen-guard-allows-checkbox
  currency-gate-vs-ledger
  secret-scan-at-sw-pr-push
  secret-patterns-single-source-allowlist
  redaction-mechanical-guard
  completion-pending-merge-decline
  merge-run-next-pr-vs-local
  orchestrator-owns-branch
  cleanup-squash-merge-aware
  spec-seed-single-owner-idempotent
  phase-resume-mid-chain
)

for fx in "${FIXTURES[@]}"; do
  case "$fx" in
    emitter-freshness-007)
      if echo "$ALL_OUT" | grep -qE 'freshness dist matches generate'; then
        echo "OK  emitter-freshness-007"
      else
        echo "FAIL emitter-freshness-007"
        FAIL=1
      fi
      ;;
    freshness)
      continue
      ;;
    *)
      if echo "$ALL_OUT" | grep -qE "OK  $fx"; then
        echo "OK  prd-007-fixture-registry:$fx"
      else
        echo "FAIL prd-007-fixture-registry:$fx"
        FAIL=1
      fi
      ;;
  esac
done

# Documentation presence (R37) — any 007-docs-* OK line
if echo "$ALL_OUT" | grep -qE 'OK  007-docs-'; then
  echo "OK  007-docs-presence"
else
  echo "FAIL 007-docs-presence"
  FAIL=1
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "prd-007 fixture registry: all scenarios present"
  exit 0
fi
echo "prd-007 fixture registry: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
