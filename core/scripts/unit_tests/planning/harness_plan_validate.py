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
# Plan-validation gate fixtures (PRD 022 phase 3 — R6, R32, R33, R25).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WAVE="$ROOT/scripts/wave.sh"
VALIDATE="$ROOT/scripts/wave_plan_validate.py"
FIX="$ROOT/scripts/test/fixtures/plan-validate"
WF="$ROOT/.cursor/workflow.config.json"
TASK_FROZEN="$ROOT/docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md"
FAIL=0

mkdir -p "$FIX"

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

CANONICAL_STEPS='["sw-tmp-init","sw-execute","sw-verify","verification-gate","sw-review","sw-simplify","gap-check","sw-commit","sw-pr","sw-watch-ci","sw-stabilize","sw-ready","sw-tmp-clean"]'

# --- plan-validate-unknown-step-rejected ---
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship \
  --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-fake-unknown\",\"sw-execute\"]}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject' and any('unknown' in r for r in d['reasons'])";
then
  ok "plan-validate-unknown-step-rejected"
else
  bad "plan-validate-unknown-step-rejected"
fi

# --- plan-validate-ambiguous-rejected ---
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship \
  --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-execute\",\"sw-execute\"],\"partialOrder\":true}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='ambiguous'";
then
  ok "plan-validate-ambiguous-rejected"
else
  bad "plan-validate-ambiguous-rejected"
fi

# --- plan-validate-signal-divergence-rejected ---
SIG='{"version":1,"derived_tags":["docs"],"file_paths":["auth/session.ts"]}'
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship \
  --signal-context "$SIG" \
  --task-file-paths "auth/session.ts" \
  --proposal "{\"steps\":$CANONICAL_STEPS,\"signal_context\":{\"version\":1,\"derived_tags\":[\"docs\"],\"file_paths\":[\"payments/checkout.ts\"]}}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='reject' and any('diverge' in r for r in d['reasons'])";
then
  ok "plan-validate-signal-divergence-rejected"
else
  bad "plan-validate-signal-divergence-rejected"
fi

# --- phase-fallback-canonical-chain ---
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship \
  --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-commit\",\"sw-execute\"]}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='reject'
fb=d.get('fallback') or {}
assert fb.get('fallback')=='canonical-chain'
assert 'sw-verify' in fb.get('steps',[])
";
then
  ok "phase-fallback-canonical-chain"
else
  bad "phase-fallback-canonical-chain"
fi

# --- Build frozen plan for wave fixtures ---
FROZEN_PLAN="$FIX/frozen-plan.json"
"$WAVE" plan --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md --dry-run >"$FROZEN_PLAN" 2>/dev/null || true
if [[ ! -s "$FROZEN_PLAN" ]]; then
  bad "wave-fixture-setup: frozen plan"
else
  ok "wave-fixture-setup: frozen plan"
fi

# --- wave-fallback-canonical-waves ---
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier wave \
  --frozen-plan "$FROZEN_PLAN" \
  --proposal "{\"waves\":[[\"1\",\"2\",\"3\"]]}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='reject'
fb=d.get('fallback') or {}
assert fb.get('fallback')=='canonical-waves'
assert fb.get('waves')
";
then
  ok "wave-fallback-canonical-waves"
else
  bad "wave-fallback-canonical-waves"
fi

# --- wave-fallback-schedule-overceiling ---
# Use a synthetic wave with 5 phases and ceiling 2
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier wave --ceiling 2 \
  --frozen-plan "$FROZEN_PLAN" \
  --proposal "{\"waves\":[[\"1\",\"2\",\"3\",\"4\",\"5\"]]}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='reject'
fb=d.get('fallback') or {}
assert fb.get('fallback')=='schedule'
assert fb.get('schedule')
";
then
  ok "wave-fallback-schedule-overceiling"
else
  bad "wave-fallback-schedule-overceiling"
fi

# --- wave-undeclared-overlap-serialized ---
OVERLAP_TASK="$FIX/tasks-overlap.md"
cat >"$OVERLAP_TASK" <<'EOF'
---
frozen: true
topic: overlap-test
---
### 1. First
- [ ] 1.1 Touch shared
  - **File:** docs/prds/INDEX.md
### 2. Second
- [ ] 2.1 Also touch shared
  - **File:** docs/prds/INDEX.md
EOF
if OUT=$(python3 "$VALIDATE" "$ROOT" serialize-overlaps --task-list "$OVERLAP_TASK" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('fallback')=='contention-serialized'
waves=d.get('waves') or []
assert len(waves)>=2
flat=[p for w in waves for p in w]
assert '1' in flat and '2' in flat
# serialized: not in same wave
for w in waves:
    if '1' in w and '2' in w:
        raise SystemExit(1)
";
then
  ok "wave-undeclared-overlap-serialized"
else
  bad "wave-undeclared-overlap-serialized"
fi

# --- plan rejection breaker (N consecutive) ---
STATE_TMP=$(mktemp)
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship --phase-id 3 \
  --record-rejection --state-path "$STATE_TMP" \
  --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-fake\"]}" 2>/dev/null); then
  :
fi
for _ in 1 2; do
  python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship --phase-id 3 \
    --record-rejection --state-path "$STATE_TMP" \
    --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-fake\"]}" >/dev/null 2>&1 || true
done
if OUT=$(python3 "$VALIDATE" "$ROOT" validate --tier phase --phase-type ship --phase-id 3 \
  --record-rejection --state-path "$STATE_TMP" \
  --proposal "{\"steps\":[\"sw-tmp-init\",\"sw-fake\"]}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('breakerTripped') is True
assert d.get('halt',{}).get('cause')=='plan-rejection-breaker'
";
then
  ok "plan-rejection-breaker-trips"
else
  bad "plan-rejection-breaker-trips"
fi
rm -f "$STATE_TMP"

# --- wave.sh plan validate routing ---
if OUT=$("$WAVE" plan validate --tier phase --phase-type ship \
  --proposal "{\"steps\":$CANONICAL_STEPS}" 2>/dev/null) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'";
then
  ok "wave-sh-plan-validate-routing"
else
  bad "wave-sh-plan-validate-routing"
fi

# --- bare plan still routes to wave_deliver ---
if OUT=$("$WAVE" plan --task-list docs/prds/004-wave-phase-orchestrator/tasks-004-wave-phase-orchestrator.md --dry-run 2>/dev/null) \
  && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['mode']=='phase'";
then
  ok "wave-sh-bare-plan-routing"
else
  bad "wave-sh-bare-plan-routing"
fi

# --- verify.test registration ---
if grep -q 'plan-validate-fixtures' "$ROOT/core/sw-reference/suite-registry.json" && grep -q 'scripts/unit_tests/planning' "$ROOT/core/sw-reference/suite-registry.json" 2>/dev/null; then
  ok "plan-validate-verify-registration"
else
  bad "plan-validate-verify-registration"
fi

if [[ "$FAIL" -eq 0 ]]; then
  echo "plan-validate fixtures: all passed"
  exit 0
fi
echo "plan-validate fixtures: $FAIL failure(s)"
exit 1

"""

if __name__ == "__main__":
    raise SystemExit(main())
