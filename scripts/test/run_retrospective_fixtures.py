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
        p for p in (str(root / "scripts"), env.get("PYTHONPATH", "")) if p
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
# Fixtures for PRD 014 retrospective command consolidation (R1–R12).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
WC="$ROOT/scripts/wave_compound.py"
LOOP="$ROOT/scripts/wave_deliver_loop.py"
RETROSPECTIVE="$(content_path commands/sw-retrospective.md)"
COMPOUND="$(content_path commands/sw-compound.md)"
COMPOUND_SHIP="$(content_path commands/sw-compound-ship.md)"
CONDUCTOR="$(content_path skills/conductor/SKILL.md)"
DELIVER="$(content_path skills/deliver/SKILL.md)"
NAMING="$(content_path rules/sw-naming.mdc)"
SCHEMA="$ROOT/.sw/config.schema.json"
WF="$ROOT/.cursor/workflow.config.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- retrospective-single-entry (R1) ---
if [[ -f "$RETROSPECTIVE" ]] && grep -q 'sw-retro' "$RETROSPECTIVE" && \
   grep -q 'memory-sync' "$RETROSPECTIVE" && grep -q 'sw-status' "$RETROSPECTIVE"; then
  ok "retrospective-single-entry"
else
  bad "retrospective-single-entry"
fi

# --- retrospective-phase-dispatch (R2) ---
if OUT=$(python3 "$WC" "$ROOT" retrospective detect-phase 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['action']=='retrospective-detect-phase'
assert d['phase'] in ('pre-merge','post-merge')
assert '/sw-retrospective' in d['invoke']
"; then
  ok "retrospective-phase-dispatch: detect-phase"
else
  bad "retrospective-phase-dispatch: detect-phase"
fi

if grep -q '\-\-pre-merge' "$RETROSPECTIVE" && grep -q '\-\-post-merge' "$RETROSPECTIVE"; then
  ok "retrospective-phase-dispatch: flags documented"
else
  bad "retrospective-phase-dispatch: flags documented"
fi

# --- retrospective-atomics-internal (R3) ---
if grep -q 'internal' "$COMPOUND" && grep -q 'deprecated' "$COMPOUND" && \
   grep -q 'skills/compound/SKILL.md' "$RETROSPECTIVE"; then
  ok "retrospective-atomics-internal"
else
  bad "retrospective-atomics-internal"
fi

# --- compound-alias-deprecation (R4) ---
if grep -q 'deprecated' "$COMPOUND_SHIP" && grep -q '/sw-retrospective' "$COMPOUND_SHIP" && \
   grep -q 'deprecated' "$COMPOUND"; then
  ok "compound-alias-deprecation"
else
  bad "compound-alias-deprecation"
fi

# --- compound-rename-propagation (R5) ---
if grep -q '/sw-retrospective' "$CONDUCTOR" && grep -q '/sw-retrospective' "$DELIVER" && \
   grep -q '/sw-retrospective' "$NAMING" && \
   python3 -c "
import json
wf=json.load(open('$WF'))
assert 'sw-retrospective' in wf.get('models',{}).get('routing',{}).get('commands',{})
"; then
  ok "compound-rename-propagation"
else
  bad "compound-rename-propagation"
fi

# --- retrospective-pending-merge (R6) ---
FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
cd "$FIX"
git init -q && git config user.email t@t.com && git config user.name T
mkdir -p docs/prds .cursor
echo '| Date | PRD | Phase | Notes |' > docs/prds/COMPLETION-LOG.md
echo '|---|---|---|---|' >> docs/prds/COMPLETION-LOG.md
git add docs/prds && git commit -q -m init && git branch -m feat/demo
if python3 "$WC" "$FIX" retrospective record-premerge --prd 014 --phase demo >/dev/null 2>&1 && \
   python3 -c "
import json, sys
sys.path.insert(0, '$ROOT/scripts')
from pathlib import Path
from wave_state import load_deliver_state
s = load_deliver_state(Path('.'), target='feat/demo')
assert s['completion']['status']=='completed-pending-merge'
"; then
  ok "retrospective-pending-merge"
else
  bad "retrospective-pending-merge"
fi

# --- retrospective-memory-fail-closed (R7) ---
if grep -q 'fail-closed' "$RETROSPECTIVE" && grep -q 'memory-preflight' "$RETROSPECTIVE"; then
  ok "retrospective-memory-fail-closed"
else
  bad "retrospective-memory-fail-closed"
fi

# --- retrospective-rule-class-gated (R8) ---
if grep -q 'human-gated' "$RETROSPECTIVE" && grep -q 'Never auto-promote rule-class' "$RETROSPECTIVE"; then
  ok "retrospective-rule-class-gated"
else
  bad "retrospective-rule-class-gated"
fi

# --- retrospective-conductor-single-source (R9) ---
if grep -q 'retrospective' "$CONDUCTOR" && grep -q '/sw-retrospective --pre-merge' "$CONDUCTOR" && \
   grep -q '/sw-retrospective --pre-merge' "$DELIVER"; then
  ok "retrospective-conductor-single-source"
else
  bad "retrospective-conductor-single-source"
fi

# --- compound-autonomy-knob (R10) ---
if OUT=$(python3 "$WC" "$ROOT" retrospective autonomy 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['mode'] in ('supervised','auto')
assert d['safetyGates']['memoryFailClosed'] is True
assert d['safetyGates']['ruleClassHumanGated'] is True
" && python3 -c "
import json
s=json.load(open('$SCHEMA'))
assert 'compound' in s['properties']
assert s['properties']['compound']['properties']['autonomy']['enum']==['supervised','auto']
"; then
  ok "compound-autonomy-knob"
else
  bad "compound-autonomy-knob"
fi

# --- retrospective-no-false-complete (R11) ---
if grep -q '\-\-require-merge' "$RETROSPECTIVE" && grep -q 'completed-pending-merge' "$RETROSPECTIVE"; then
  ok "retrospective-no-false-complete"
else
  bad "retrospective-no-false-complete"
fi

# --- retrospective-emitter-freshness (R12) ---
if [[ -d "$ROOT/dist/cursor" ]] && [[ -d "$ROOT/dist/claude-code" ]]; then
  set +e
  python3 -m sw generate --all >/dev/null 2>&1
  set -e
  if git -C "$ROOT" diff --exit-code -- dist/cursor dist/claude-code >/dev/null 2>&1; then
    ok "retrospective-emitter-freshness"
  else
    bad "retrospective-emitter-freshness"
  fi
else
  bad "retrospective-emitter-freshness: dist missing"
fi

# --- retrospective-docs-presence (R12) ---
GUIDES=0
for f in "$ROOT/docs/guides/workflows.md" "$ROOT/docs/guides/configuration.md"; do
  if [[ -f "$f" ]] && grep -q 'sw-retrospective' "$f" && grep -q 'compound.autonomy' "$f"; then
    GUIDES=$((GUIDES + 1))
  fi
done
if [[ "$GUIDES" -ge 2 ]]; then
  ok "retrospective-docs-presence"
else
  bad "retrospective-docs-presence"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "retrospective fixtures: FAIL"
  exit 1
fi
echo "retrospective fixtures: PASS"
exit 0

"""

if __name__ == "__main__":
    raise SystemExit(main())
