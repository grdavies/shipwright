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

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


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
# In-flight doc-currency fixtures (PRD 032 phase 7 — R15).
# Hard-block on drift across the five operator-facing surfaces.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

require_patterns() {
  local label="$1"
  local file="$2"
  shift 2
  local missing=0
  for pat in "$@"; do
    if ! grep -qE "$pat" "$file"; then
      bad "$label: missing pattern $pat in $file"
      missing=1
    fi
  done
  [[ "$missing" -eq 0 ]]
}

forbid_pattern() {
  local label="$1"
  local file="$2"
  local pat="$3"
  if grep -qE "$pat" "$file"; then
    bad "$label: forbidden pattern $pat in $file"
    return 1
  fi
  return 0
}

check_surface() {
  local rel="$1"
  local core="$ROOT/core/$rel"
  [[ -f "$core" ]] || { bad "inflight-doc-currency: missing core/$rel"; return 1; }
  for dist in "$ROOT/dist/cursor/$rel" "$ROOT/dist/claude-code/$rel"; do
    if [[ ! -f "$dist" ]]; then
      bad "inflight-doc-currency: missing $dist"
      return 1
    fi
    if ! cmp -s "$core" "$dist"; then
      bad "inflight-doc-currency: dist drift $rel"
      return 1
    fi
  done
  printf '%s\n' "$core"
}

DOC_CURRENCY_OK=true

AMEND="$(check_surface commands/sw-amend.md)" || DOC_CURRENCY_OK=false
if [[ -n "${AMEND:-}" ]]; then
  require_patterns "inflight-doc-currency:sw-amend" "$AMEND" \
    'authoring-guard\.py preflight' \
    '\-\-handoff' \
    'refuses in-place amend|Complete-unit refusal' \
    'planned.*in-progress|in-progress.*planned' \
    'extends:|supersedes:' || DOC_CURRENCY_OK=false
fi

TASKS="$(check_surface commands/sw-tasks.md)" || DOC_CURRENCY_OK=false
if [[ -n "${TASKS:-}" ]]; then
  require_patterns "inflight-doc-currency:sw-tasks" "$TASKS" \
    'authoring-guard\.py preflight' \
    '\-\-handoff' \
    'Complete-unit refusal|complete unit' || DOC_CURRENCY_OK=false
fi

PRD="$(check_surface commands/sw-prd.md)" || DOC_CURRENCY_OK=false
if [[ -n "${PRD:-}" ]]; then
  require_patterns "inflight-doc-currency:sw-prd" "$PRD" \
    'authoring-guard\.py preflight' \
    '\-\-handoff' \
    'Complete-unit refusal|complete unit' || DOC_CURRENCY_OK=false
fi

FREEZE="$(check_surface commands/sw-freeze.md)" || DOC_CURRENCY_OK=false
if [[ -n "${FREEZE:-}" ]]; then
  require_patterns "inflight-doc-currency:sw-freeze" "$FREEZE" \
    'pre-commit-completed-unit\.py' \
    'R9/R12|R9.*R12' \
    'complete.unit|Complete-unit' \
    'graceful-degraded|structural-status' \
    'reconcile-generation token' || DOC_CURRENCY_OK=false
fi

DELIVER="$(check_surface skills/deliver/SKILL.md)" || DOC_CURRENCY_OK=false
if [[ -n "${DELIVER:-}" ]]; then
  require_patterns "inflight-doc-currency:deliver-skill" "$DELIVER" \
    'inFlight' \
    'lock-acquire' \
    'orchestrator-provision' \
    'inflight-signal-clear|cleared at run completion' \
    'not.*stored in the tuple|PRD 033 derives' \
    'SW_INDEX_REGION_WRITER=deliver' || DOC_CURRENCY_OK=false
  forbid_pattern "inflight-doc-currency:deliver-skill" "$DELIVER" \
    'INDEX never uses.*in-progress' || DOC_CURRENCY_OK=false
fi

if $DOC_CURRENCY_OK; then
  ok "inflight-doc-currency"
else
  bad "inflight-doc-currency"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
