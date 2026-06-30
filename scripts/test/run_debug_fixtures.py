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
# Fixture tests for debugging workstream (plan 004).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
REDACT="$ROOT/scripts/memory-redact.sh"
RCA="$(content_path skills/rca-core/SKILL.md)"
FAIL=0

# --- U1: debug entry implemented (not deferred stub) ---
if grep -q '## Debug entry procedure' "$RCA" && \
   ! grep -q 'Deferred to debugging-workstream' "$RCA" && \
   grep -q 'Causal-chain gate' "$RCA" && \
   grep -q '## Stabilize entry procedure' "$RCA"; then
  echo "OK  rca-core debug entry + stabilize preserved"
else
  echo "FAIL rca-core missing debug entry or still stubbed"
  FAIL=1
fi

DEBUG_INPUTS="$(content_path skills/rca-core/references/debug-inputs.md)"
if [[ -f "$DEBUG_INPUTS" ]] && \
   grep -q 'sentry' "$DEBUG_INPUTS"; then
  echo "OK  debug-inputs reference"
else
  echo "FAIL debug-inputs.md"
  FAIL=1
fi

# --- U1: hard stops documented ---
if grep -q 'maxIterations' "$RCA" && grep -q 'No progress' "$RCA"; then
  echo "OK  rca-core hard stops"
else
  echo "FAIL rca-core hard stops"
  FAIL=1
fi

# --- U2: sentry recipe exists ---
SENTRY_MD="$(content_path skills/debug/references/sentry.md)"
if [[ -f "$SENTRY_MD" ]] && \
   grep -q 'memory-redact' "$SENTRY_MD" && \
   grep -qi 'degrad' "$SENTRY_MD"; then
  echo "OK  sentry MCP recipe + degradation"
else
  echo "FAIL sentry.md"
  FAIL=1
fi

# --- U2: Sentry-like payload redaction (ghp token in breadcrumb) ---
SENTRY_LIKE=$'breadcrumb: user clicked\nghp_abcdefghijklmnopqrstuvwxyz1234567890ABCD\nemail: leak@corp.example.com'
SCRUBBED=$(echo "$SENTRY_LIKE" | bash "$REDACT")
if [[ "$SCRUBBED" == *'[REDACTED:'* ]] && [[ "$SCRUBBED" != *'ghp_abc'* ]] && [[ "$SCRUBBED" != *'leak@corp'* ]]; then
  echo "OK  sentry payload redaction"
else
  echo "FAIL sentry payload redaction got: $SCRUBBED"
  FAIL=1
fi

# --- U3: sw-debug command + skill ---
SW_DEBUG="$(content_path commands/sw-debug.md)"
if [[ -f "$SW_DEBUG" ]] && \
   grep -qi 'not implement' "$SW_DEBUG" && \
   grep -q 'memory-preflight' "$SW_DEBUG"; then
  echo "OK  sw-debug command boundary"
else
  echo "FAIL sw-debug.md"
  FAIL=1
fi

DEBUG_SKILL="$(content_path skills/debug/SKILL.md)"
if [[ -f "$DEBUG_SKILL" ]] && \
   grep -q 'rca-core' "$DEBUG_SKILL" && \
   grep -qi 'trivial fast-path' "$DEBUG_SKILL"; then
  echo "OK  debug skill orchestrator"
else
  echo "FAIL skills/debug/SKILL.md"
  FAIL=1
fi

# --- U4: routing to 003/002 ---
if grep -q '/sw-worktree' "$DEBUG_SKILL" && \
   grep -q '/sw-brainstorm' "$DEBUG_SKILL" && \
   grep -q 'surface:debug-route' "$DEBUG_SKILL"; then
  echo "OK  debug downstream routing"
else
  echo "FAIL debug routing sections"
  FAIL=1
fi

# --- sw-naming debug boundary ---
SW_NAMING="$(content_path rules/sw-naming.mdc)"
if grep -q '/sw-debug' "$SW_NAMING" && \
   grep -q 'Debug orchestrator boundary' "$SW_NAMING"; then
  echo "OK  sw-naming debug boundary"
else
  echo "FAIL sw-naming debug boundary"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL debug fixtures passed"
else
  echo "SOME debug fixtures FAILED"
  exit 1
fi

"""

if __name__ == "__main__":
    raise SystemExit(main())
