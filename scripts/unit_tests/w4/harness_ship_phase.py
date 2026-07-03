#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import repo_root
from _harness_patch import harness_subprocess_env as _harness_env
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
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
# Fixtures for step-granular /sw-ship phase-mode resume (PRD 007 Phase 6 — R58).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STEPS_SH="$ROOT/scripts/ship-phase-steps.sh"
STATE_SH="$ROOT/scripts/shipwright-state.sh"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

cd "$FIX"
git init -q
git config user.email test@test.com
git config user.name Test
git commit --allow-empty -q -m init
mkdir -p .cursor/sw-deliver-runs/alpha

export SW_PHASE_SLUG=alpha
export SW_RUN_DIR="$FIX/.cursor/sw-deliver-runs/alpha"

# Seed mid-chain state: completed through sw-verify, currently at sw-review
bash "$STEPS_SH" init --phase alpha --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS_SH" advance --step sw-tmp-init --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS_SH" advance --step sw-execute --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS_SH" advance --step sw-verify --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS_SH" advance --step verification-gate --out "$SW_RUN_DIR/ship-steps.json" >/dev/null

# --- phase-resume-mid-chain ---
if OUT=$(bash "$STEPS_SH" resolve-resume --out "$SW_RUN_DIR/ship-steps.json" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['nextStep']=='sw-review', d
assert d['source']=='persisted-current', d
"; then
  ok "phase-resume-mid-chain: fresh agent resumes at sw-review"
else
  bad "phase-resume-mid-chain: fresh agent resumes at sw-review"
fi

# CLI --from overrides persisted state
if OUT=$(bash "$STEPS_SH" resolve-resume --from sw-stabilize --out "$SW_RUN_DIR/ship-steps.json" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['nextStep']=='sw-stabilize' and d['source']=='cli-from'
"; then
  ok "phase-resume-mid-chain: --from overrides persisted currentStep"
else
  bad "phase-resume-mid-chain: --from overrides persisted currentStep"
fi

# Attempt counter increments
bash "$STEPS_SH" attempt --step sw-review --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
bash "$STEPS_SH" attempt --step sw-review --out "$SW_RUN_DIR/ship-steps.json" >/dev/null
if bash "$STEPS_SH" get --out "$SW_RUN_DIR/ship-steps.json" 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['state']['stepAttempts']['sw-review']==2
"; then
  ok "phase-resume-mid-chain: per-step attempt counters persist"
else
  bad "phase-resume-mid-chain: per-step attempt counters persist"
fi

# sync-ship-steps merges into shipwright.json
if bash "$STATE_SH" sync-ship-steps >/dev/null 2>&1 && \
   bash "$STATE_SH" read 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
ps=d.get('phaseShip',{})
assert ps.get('currentStep')=='sw-review'
assert ps.get('lastCompletedStep')=='verification-gate'
"; then
  ok "phase-resume-mid-chain: sync-ship-steps writes phaseShip to shipwright.json"
else
  bad "phase-resume-mid-chain: sync-ship-steps writes phaseShip to shipwright.json"
fi

# ship-phase-status embeds shipSteps when present
SHIP_STATUS="$ROOT/scripts/ship-phase-status.sh"
if OUT=$("$SHIP_STATUS" --verdict merge-ready-green --phase alpha --out "$SW_RUN_DIR/status.json" 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('shipSteps',{}).get('currentStep')=='sw-review'
assert 'shipStepsPath' in d
"; then
  ok "phase-resume-mid-chain: status.json embeds shipSteps snapshot"
else
  bad "phase-resume-mid-chain: status.json embeds shipSteps snapshot"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "ship-phase fixtures: all passed"
  exit 0
fi
echo "ship-phase fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
