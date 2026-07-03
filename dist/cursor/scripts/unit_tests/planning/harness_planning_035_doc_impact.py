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
# PRD 035 phase 6 — doc-impact acceptance (R21) + no-regression on delivery gates (R16).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SW_PRD="$(content_path commands/sw-prd.md)"
SW_TASKS="$(content_path commands/sw-tasks.md)"
SW_DOC="$(content_path commands/sw-doc.md)"
SW_FEEDBACK="$(content_path commands/sw-feedback.md)"
ROUTE_RECORD="$(content_path skills/feedback/references/route-record.md)"
SW_NAMING="$(content_path rules/sw-naming.mdc)"
GIT_WF="$(content_path skills/git-workflow/SKILL.md)"
SW_GIT="$(content_path rules/sw-git-conventions.mdc)"
CONDUCTOR="$(content_path skills/conductor/SKILL.md)"
SCHEMA="$ROOT/core/sw-reference/config.schema.json"
WF_SW="$ROOT/.sw/workflow.config.example.json"
WF_CORE="$ROOT/core/sw-reference/workflow.config.example.json"
CONFIG_GUIDE="$ROOT/docs/guides/configuration.md"
WORKFLOWS="$ROOT/docs/guides/workflows.md"
COMMANDS="$ROOT/docs/guides/commands.md"

check() {
  local name="$1" file="$2" pattern="$3"
  if grep -qE "$pattern" "$file" 2>/dev/null; then ok "$name"; else bad "$name"; fi
}

check_doc() {
  local label="$1" file="$2"
  shift 2
  if [[ ! -f "$file" ]]; then
    bad "doc-currency-035:$label:missing:$file"
    return
  fi
  for term in "$@"; do
    if ! grep -qiE "$term" "$file" 2>/dev/null; then
      bad "doc-currency-035:$label:missing:'$term'"
      return
    fi
  done
  ok "doc-currency-035:$label"
}

check "doc-currency-035:sw-prd-pull-in" "$SW_PRD" "planning-related[.]py scan --mode creation"
check "doc-currency-035:sw-prd-confirm-list" "$SW_PRD" "confirm-list"
check "doc-currency-035:sw-tasks-rescan" "$SW_TASKS" "planning-related[.]py scan --mode tasks-rescan"
check "doc-currency-035:sw-doc-reconciler" "$SW_DOC" "planning-graph[.]py reconcile"
check "doc-currency-035:sw-doc-two-track" "$SW_DOC" "docs-edit-route[.]py"
check "doc-currency-035:sw-doc-posture" "$SW_DOC" "planning\.autonomy"
check "doc-currency-035:sw-feedback-gap-unit" "$SW_FEEDBACK" "planning_gap_capture"
check "doc-currency-035:route-record-gap-unit" "$ROUTE_RECORD" "docs/planning/<gap-unit-id>"
check "doc-currency-035:sw-naming-gap-unit" "$SW_NAMING" "planning_gap_capture"
check "doc-currency-035:git-workflow-two-track" "$GIT_WF" "Two-track doc edits"
check "doc-currency-035:sw-git-two-track" "$SW_GIT" "Two-track doc edits"
check "doc-currency-035:conductor-full-conductor" "$CONDUCTOR" "Bounded planning full-conductor"
check "doc-currency-035:conductor-mutation-budget" "$CONDUCTOR" "planning-mutation-budget"
check "doc-currency-035:conductor-no-nested" "$CONDUCTOR" "No nested dispatch"

check_doc "config-schema" "$SCHEMA" 'planning\.autonomy' 'fullConductor' 'maintenance-only'
check_doc "workflow-example-sw" "$WF_SW" '"autonomy"' 'maintenance-only' 'fullConductor'
check_doc "workflow-example-core" "$WF_CORE" '"autonomy"' 'maintenance-only' 'fullConductor'
check_doc "configuration-guide" "$CONFIG_GUIDE" 'Planning autonomy \(PRD 035\)' 'planning\.autonomy' 'full-conductor'
check_doc "workflows-guide" "$WORKFLOWS" 'Planning autonomy and two-track edits \(PRD 035\)' 'confirm-list' 'docs-edit-route'
check_doc "commands-guide" "$COMMANDS" 'Planning surface \(PRD 035\)' 'planning-related[.]py' 'planning_gap_capture'

[[ "$FAIL" -eq 0 ]] && ok "doc-currency-035"

CORPUS="$ROOT/scripts/test/fixtures/planning-currency/migrated-corpus"
PRD_CORPUS="$CORPUS/prd-099-fixture-prd-prd-fixture-prd.md"
TASKS_CORPUS="$CORPUS/tasks-099-fixture-prd.md"

if [[ -f "$PRD_CORPUS" && -f "$TASKS_CORPUS" ]]; then
  if bash "$ROOT/scripts/spec-rigor-check.py" --artifact prd --path "$PRD_CORPUS" --tier full >/dev/null 2>&1 && \
     bash "$ROOT/scripts/spec-rigor-check.py" --artifact tasks --path "$TASKS_CORPUS" --prd "$PRD_CORPUS" >/dev/null 2>&1 && \
     bash "$ROOT/scripts/traceability-check.py" --prd "$PRD_CORPUS" --tasks "$TASKS_CORPUS" >/dev/null 2>&1; then
    ok "no-regression-035:migrated-corpus-gates"
  else
    bad "no-regression-035:migrated-corpus-gates"
  fi
else
  bad "no-regression-035:corpus-missing"
fi

if grep -qE 'does not bypass.*main|human merge gate|never merges' "$ROOT/core/commands/sw-ship.md" && \
   grep -qE 'does not bypass.*main|human merge gate|terminal merge gate' "$ROOT/core/commands/sw-deliver.md" && \
   grep -qE 'frozen: true|Irreversible|/sw-amend' "$ROOT/core/commands/sw-freeze.md"; then
  ok "no-regression-035:frozen-workflow-invariants"
else
  bad "no-regression-035:frozen-workflow-invariants"
fi

if grep -q 'R16 no-regression' "$ROOT/scripts/spec-rigor-check.py" && \
   grep -q 'R16 no-regression' "$ROOT/scripts/traceability-check.py"; then
  ok "no-regression-035:gate-script-contract"
else
  bad "no-regression-035:gate-script-contract"
fi

python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
ids = {e['id'] for e in data.get('fixtures', [])}
need = {'authoring-guard-fixtures', 'planning-currency-fixtures', 'doc-fixtures'}
assert need <= ids
" "$ROOT/core/sw-reference/pr-test-plan.manifest.json" && ok "no-regression-035:frozen-doc-gate-fixtures" || bad "no-regression-035:frozen-doc-gate-fixtures"

[[ "$FAIL" -eq 0 ]] && ok "no-regression-035"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
