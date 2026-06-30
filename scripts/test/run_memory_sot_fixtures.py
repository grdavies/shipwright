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
# Fixtures for PRD 015 memory source-of-truth (R1–R12).
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

MEMORY_SKILL="$(content_path skills/memory/SKILL.md)"
GUARDRAILS="$(content_path rules/memory-guardrails.mdc)"
LAYOUT="$ROOT/.sw/layout.md"
SCHEMA="$ROOT/.sw/config.schema.json"
WF="$ROOT/.cursor/workflow.config.json"
FAIL=0

ok()  { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- memory-sot-resolve-auto (R1, R2) ---
if OUT=$(bash "$ROOT/scripts/memory-sot.sh" resolve --class decision --json 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['verdict']=='pass'
assert d['effective'] in ('repo','memory')
assert d['sourceOfTruth'] in ('repo','memory','auto')
"; then
  ok "memory-sot-resolve-auto"
else
  bad "memory-sot-resolve-auto"
fi

if python3 -c "
import json
s=json.load(open('$SCHEMA'))
mem=s['properties']['memory']['properties']
assert 'sourceOfTruth' in mem
assert set(mem['sourceOfTruth']['enum'])=={'repo','memory','auto'}
"; then
  ok "memory-sot-resolve-auto: schema knob"
else
  bad "memory-sot-resolve-auto: schema knob"
fi

# --- memory-sot-decision-scope-only (R3) ---
if OUT=$(bash "$ROOT/scripts/memory-sot.sh" resolve --class learning --json 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['effective']=='distillation'
"; then
  ok "memory-sot-decision-scope-only"
else
  bad "memory-sot-decision-scope-only"
fi

# --- memory-sot-pointer-inversion (R6) ---
if OUT=$(bash "$ROOT/scripts/memory-sot.sh" pointer-recipe --path docs/decisions/001-test.md --json 2>/dev/null) && \
   echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['action']=='pointer-recipe'
assert d['authoritative'] in ('git','provider')
assert d['authoritative']!=d['nonAuthoritative']
"; then
  ok "memory-sot-pointer-inversion"
else
  bad "memory-sot-pointer-inversion"
fi

# --- memory-sot-supersede-reconcile (R7) ---
if [[ -f "$ROOT/docs/decisions/SUPERSEDED.log" ]] && \
   bash "$ROOT/scripts/reconcile.py" supersede-reconcile --json >/dev/null 2>&1 && \
   grep -q 'append-superseded' "$ROOT/scripts/reconcile.py"; then
  ok "memory-sot-supersede-reconcile"
else
  bad "memory-sot-supersede-reconcile"
fi

# --- memory-sot-snapshot-always-committed (R4, R6) ---
if [[ -x "$ROOT/scripts/memory-decision-snapshot.sh" ]] && \
   grep -q 'snapshotRole' "$ROOT/scripts/memory_decision_snapshot.py" && \
   grep -q 'authoritative' "$ROOT/scripts/memory_decision_snapshot.py"; then
  ok "memory-sot-snapshot-always-committed"
else
  bad "memory-sot-snapshot-always-committed"
fi

# --- memory-sot-freeze-offline (R5) ---
if grep -q 'provider write best-effort deferred' "$ROOT/scripts/memory_decision_snapshot.py" && \
   grep -q 'memory-decision-snapshot' "$(content_path commands/sw-freeze.md)" && \
   grep -q 'never a CI gate' "$(content_path commands/sw-freeze.md)"; then
  ok "memory-sot-freeze-offline"
else
  bad "memory-sot-freeze-offline"
fi

# --- memory-sot-compound-branch (R8) ---
if grep -q 'pointer-recipe' "$(content_path skills/compound/SKILL.md)" && \
   grep -q 'memory-SoT' "$(content_path skills/compound/SKILL.md)"; then
  ok "memory-sot-compound-branch"
else
  bad "memory-sot-compound-branch"
fi

# --- memory-sot-audit-conflict (R9, R11) ---
if [[ -x "$ROOT/scripts/memory-sot-audit.sh" ]] && \
   bash "$ROOT/scripts/memory-sot-audit.sh" audit-conflicts >/dev/null 2>&1 && \
   bash "$ROOT/scripts/memory-sot-audit.sh" legacy-reconcile-plan --target auto >/dev/null 2>&1 && \
   grep -q 'memory-sot-audit' "$(content_path commands/sw-memory-audit.md)"; then
  ok "memory-sot-audit-conflict"
else
  bad "memory-sot-audit-conflict"
fi

# --- memory-sot-redaction-fail-closed (R10) ---
if grep -q 'Fail-closed' "$MEMORY_SKILL" && \
   grep -q 'memory-redact failed' "$ROOT/scripts/memory_decision_snapshot.py"; then
  ok "memory-sot-redaction-fail-closed"
else
  bad "memory-sot-redaction-fail-closed"
fi

# --- memory-sot-default-no-change (R2, R11) ---
if grep -q 'auto.*in-repo' "$MEMORY_SKILL" && \
   grep -q 'no behavior change\|preserves today' "$MEMORY_SKILL"; then
  ok "memory-sot-default-no-change"
else
  bad "memory-sot-default-no-change"
fi

# --- memory-sot-emitter-freshness (R12) ---
if [ -d "$ROOT/dist/cursor" ] && python3 -m sw generate --all >/dev/null 2>&1 && \
   git -C "$ROOT" diff --exit-code -- dist/cursor dist/claude-code >/dev/null 2>&1; then
  ok "memory-sot-emitter-freshness"
else
  bad "memory-sot-emitter-freshness"
fi

# --- memory-sot-docs-presence (R12) ---
if grep -q 'sourceOfTruth\|Source of truth' "$MEMORY_SKILL" && \
   grep -q 'sourceOfTruth\|source of truth' "$GUARDRAILS" && \
   grep -q 'SUPERSEDED.log' "$LAYOUT" && \
   grep -q 'sourceOfTruth' "$ROOT/docs/guides/configuration.md" 2>/dev/null; then
  ok "memory-sot-docs-presence"
else
  bad "memory-sot-docs-presence"
fi

# --- verify.test registration ---
if grep -q 'run-memory-sot-fixtures.sh' "$WF" 2>/dev/null; then
  ok "memory-sot-verify-registration"
else
  bad "memory-sot-verify-registration"
fi

if [ "$FAIL" -eq 0 ]; then
  echo "ALL memory-sot fixtures passed"
else
  echo "SOME memory-sot fixtures FAILED"
fi
exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
