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
# Planning currency fixtures (PRD 031 phase 8 — R17/R25/R26/R30).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"

FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

LAYOUT_SW="$ROOT/.sw/layout.md"
LAYOUT_CORE="$ROOT/core/sw-reference/layout.md"
SCHEMA="$ROOT/core/sw-reference/config.schema.json"
WF_SW="$ROOT/.sw/workflow.config.example.json"
WF_CORE="$ROOT/core/sw-reference/workflow.config.example.json"
SPEC_RIGOR="$(content_path skills/spec-rigor/SKILL.md)"
SPEC_UNION="$(content_path skills/spec-union/SKILL.md)"
README="$ROOT/README.md"
CONFIG_GUIDE="$ROOT/docs/guides/configuration.md"
REDACT="$ROOT/scripts/memory-redact.py"
GEN="python3 -m sw"

CORPUS="$ROOT/scripts/test/fixtures/planning-currency/migrated-corpus"
PRD_CORPUS="$CORPUS/prd-099-fixture-prd-prd-fixture-prd.md"
TASKS_CORPUS="$CORPUS/tasks-099-fixture-prd.md"

PLANNING_SCRIPTS=(
  doc_format.py
  doc-format-normalize.py
  planning_status_enum.py
  planning-unit-validate.py
  planning_paths.py
  planning_paths.py
  planning_index_gen.py
  index-region-guard.py
  planning_migrate.py
  planning_path_redirect.py
  planning_legacy_projection.py
  relief-acceptance-check.py
  planning-privacy-guard.py
)

# --- copy-to-core-parity (R25) ---
if bash "$ROOT/scripts/copy-to-core.py" >/dev/null 2>&1 && \
   bash "$ROOT/scripts/test/run_core_scripts_parity_fixtures.py" >/dev/null 2>&1; then
  ok "copy-to-core-parity"
else
  bad "copy-to-core-parity"
fi

for rel in "${PLANNING_SCRIPTS[@]}"; do
  if [[ -f "$ROOT/scripts/$rel" && -f "$ROOT/core/scripts/$rel" ]] && cmp -s "$ROOT/scripts/$rel" "$ROOT/core/scripts/$rel"; then
    :
  else
    bad "copy-to-core-parity: core/scripts/$rel"
    break
  fi
done
[[ "$FAIL" -eq 0 ]] && ok "copy-to-core-parity: planning scripts mirrored"

if [[ -f "$ROOT/core/scripts/copy-to-core.py" ]] && cmp -s "$ROOT/scripts/copy-to-core.py" "$ROOT/core/scripts/copy-to-core.py"; then
  ok "copy-to-core-parity: core/scripts/copy-to-core.py"
else
  bad "copy-to-core-parity: core/scripts/copy-to-core.py"
fi

# --- emitter-freshness-planning-artifacts (R25) ---
$GEN generate --all >/dev/null 2>&1 || bad "emitter-freshness-planning-artifacts: generate failed"
HASH1=$(find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
$GEN generate --all >/dev/null 2>&1 || bad "emitter-freshness-planning-artifacts: second generate failed"
HASH2=$(find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
if [[ "$HASH1" == "$HASH2" ]]; then
  ok "emitter-freshness-planning-artifacts: generate idempotent"
else
  bad "emitter-freshness-planning-artifacts: generate hash drift"
fi

for dist in "$ROOT/dist/cursor" "$ROOT/dist/claude-code"; do
  if [[ -f "$dist/core/sw-reference/planning-unit.schema.json" ]]; then
    :
  else
    bad "emitter-freshness-planning-artifacts: missing planning-unit.schema.json in $dist"
  fi
  for rel in planning_index_gen.py planning_migrate.py planning-unit-validate.py; do
    if [[ ! -f "$dist/scripts/$rel" ]]; then
      bad "emitter-freshness-planning-artifacts: missing dist/scripts/$rel"
    fi
  done
done
[[ "$FAIL" -eq 0 ]] && ok "emitter-freshness-planning-artifacts"

# --- doc-currency-layout-config-skills-readme-guide (R26) ---
doc_currency_ok=true
for f in "$LAYOUT_SW" "$LAYOUT_CORE"; do
  grep -q 'planning-unit.schema.json' "$f" || doc_currency_ok=false
  grep -q 'docs/planning/INDEX.md' "$f" || doc_currency_ok=false
  grep -q 'Migration cutover checklist' "$f" || doc_currency_ok=false
  grep -q 'copy-to-core' "$f" || doc_currency_ok=false
done
python3 -c "import json; s=json.load(open('$SCHEMA')); assert 'planningDir' in s['properties']" || doc_currency_ok=false
for f in "$WF_SW" "$WF_CORE"; do
  grep -q '"planningDir"' "$f" || doc_currency_ok=false
done
grep -q 'doc-format-normalize' "$SPEC_RIGOR" || doc_currency_ok=false
grep -q 'planningDir' "$SPEC_RIGOR" || doc_currency_ok=false
grep -q 'doc_format.py' "$SPEC_UNION" || doc_currency_ok=false
grep -q 'planningDir' "$SPEC_UNION" || doc_currency_ok=false
grep -q 'planningDir' "$README" || doc_currency_ok=false
grep -q 'planningDir' "$CONFIG_GUIDE" || doc_currency_ok=false
grep -q 'docs/planning/INDEX.md' "$CONFIG_GUIDE" || doc_currency_ok=false
grep -q 'docs/planning/brainstorm' "$ROOT/.gitignore" || doc_currency_ok=false

if $doc_currency_ok; then
  ok "doc-currency-layout-config-skills-readme-guide"
else
  bad "doc-currency-layout-config-skills-readme-guide"
fi

# --- no-regression-migrated-corpus (R17) ---
if [[ -f "$PRD_CORPUS" && -f "$TASKS_CORPUS" ]]; then
  if bash "$ROOT/scripts/spec-rigor-check.sh" --artifact prd --path "$PRD_CORPUS" --tier full >/dev/null 2>&1 && \
     bash "$ROOT/scripts/spec-rigor-check.sh" --artifact tasks --path "$TASKS_CORPUS" --prd "$PRD_CORPUS" >/dev/null 2>&1 && \
     bash "$ROOT/scripts/traceability-check.sh" --prd "$PRD_CORPUS" --tasks "$TASKS_CORPUS" >/dev/null 2>&1; then
    ok "no-regression-migrated-corpus"
  else
    bad "no-regression-migrated-corpus"
  fi
else
  bad "no-regression-migrated-corpus: fixture corpus missing"
fi

# --- no-memory-writes-redaction-unchanged (R30) ---
if [[ -x "$REDACT" ]]; then
  OUT=$(printf 'Bearer sk-fixture_memory_redact_high_entropy_test_val_abcdefghijklmnopqrstuvwxyz' | bash "$REDACT")
  if echo "$OUT" | grep -q 'sk-fixture_memory_redact_high_entropy_test_val'; then
    bad "no-memory-writes-redaction-unchanged: redact chokepoint failed"
  else
    ok "no-memory-writes-redaction-unchanged: redact chokepoint"
  fi
else
  bad "no-memory-writes-redaction-unchanged: memory-redact.py missing"
fi

NEW_MEMORY_SURFACES=0
for rel in "${PLANNING_SCRIPTS[@]}"; do
  f="$ROOT/scripts/$rel"
  [[ -f "$f" ]] || continue
  if grep -qE 'memory-sync|memory_sync|recallium|sw-memory|memory\.provider' "$f" 2>/dev/null; then
    NEW_MEMORY_SURFACES=1
    bad "no-memory-writes-redaction-unchanged: unexpected memory surface in scripts/$rel"
  fi
done
[[ "$NEW_MEMORY_SURFACES" -eq 0 ]] && ok "no-memory-writes-redaction-unchanged: no new memory writes"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
