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
# PRD 034 Phase 7 — store/visibility emitter parity, public-unit no-regression, doc-impact acceptance.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
GEN="python3 -m sw"

SCRIPTS_034=(
  gitignore-generate.py
  gitignore_generate.py
  planning_visibility.py
  planning_store.py
  planning_materialize.py
  planning-init-seed.py
  planning-doctor.py
  visibility-resolve.py
  visibility-callsite-lint.py
  materialized-prefix-scan.py
)

PROVIDERS_034=(
  CAPABILITIES.md
  in-repo.md
  local-synced.md
  memory.md
)

check_doc() {
  local file="$1" label="$2"
  shift 2
  if [[ ! -f "$file" ]]; then
    bad "doc-impact-visibility-store:$label:missing:$file"
    return
  fi
  local text
  text="$(cat "$file")"
  for term in "$@"; do
    if ! echo "$text" | grep -qiE "$term"; then
      bad "doc-impact-visibility-store:$label:missing:'$term'"
      return
    fi
  done
  ok "doc-impact-visibility-store:$label"
}

# --- store-emitter-parity (R22) ---
for rel in "${SCRIPTS_034[@]}"; do
  if [[ -f "$ROOT/scripts/$rel" && -f "$ROOT/core/scripts/$rel" ]] && cmp -s "$ROOT/scripts/$rel" "$ROOT/core/scripts/$rel"; then
    :
  else
    bad "store-emitter-parity:core/scripts/$rel"
  fi
done
for rel in "${PROVIDERS_034[@]}"; do
  if [[ -f "$ROOT/core/providers/planning-store/$rel" ]]; then
    :
  else
    bad "store-emitter-parity:core/providers/planning-store/$rel"
  fi
done
[[ "$FAIL" -eq 0 ]] && ok "store-emitter-parity:copy-to-core"

python3 -c "
import json
from pathlib import Path
for p in (Path('$ROOT/.sw/config.schema.json'), Path('$ROOT/core/sw-reference/config.schema.json')):
    s = json.loads(p.read_text())
    planning = s['properties']['planning']['properties']
    assert 'visibilityProfile' in planning
    assert 'store' in planning
    store = planning['store']['properties']
    assert 'backend' in store
" && ok "store-emitter-parity:schema-keys" || bad "store-emitter-parity:schema-keys"

$GEN generate --all >/dev/null 2>&1 || bad "store-emitter-parity:generate"
for dist in "$ROOT/dist/cursor" "$ROOT/dist/claude-code"; do
  for rel in "${SCRIPTS_034[@]}"; do
    [[ -f "$dist/scripts/$rel" ]] || bad "store-emitter-parity:missing:$dist/scripts/$rel"
  done
  for rel in "${PROVIDERS_034[@]}"; do
    [[ -f "$dist/providers/planning-store/$rel" ]] || bad "store-emitter-parity:missing:$dist/providers/planning-store/$rel"
  done
done
[[ "$FAIL" -eq 0 ]] && ok "store-emitter-parity:dist-propagation"

python3 "$ROOT/scripts/unit_tests/meta/harness_emitter.py" >/dev/null 2>&1 && ok "store-emitter-parity:emitter-freshness" || bad "store-emitter-parity:emitter-freshness"

# --- public-unit-no-regression (R17) ---
CORPUS="$ROOT/scripts/test/fixtures/planning-currency/migrated-corpus"
PRD_CORPUS="$CORPUS/prd-099-fixture-prd-prd-fixture-prd.md"
TASKS_CORPUS="$CORPUS/tasks-099-fixture-prd.md"
if [[ -f "$PRD_CORPUS" && -f "$TASKS_CORPUS" ]]; then
  bash "$ROOT/scripts/spec-rigor-check.sh" --artifact prd --path "$PRD_CORPUS" --tier full >/dev/null 2>&1 &&   bash "$ROOT/scripts/spec-rigor-check.sh" --artifact tasks --path "$TASKS_CORPUS" --prd "$PRD_CORPUS" >/dev/null 2>&1 &&   bash "$ROOT/scripts/traceability-check.sh" --prd "$PRD_CORPUS" --tasks "$TASKS_CORPUS" >/dev/null 2>&1 &&   ok "public-unit-no-regression:migrated-corpus-gates" || bad "public-unit-no-regression:migrated-corpus-gates"
else
  bad "public-unit-no-regression:corpus-missing"
fi

if grep -qE 'does not bypass.*main|human merge gate|never merges' "$ROOT/core/commands/sw-ship.md" && \
   grep -qE 'does not bypass.*main|human merge gate' "$ROOT/core/commands/sw-deliver.md"; then
  ok "public-unit-no-regression:human-merge-gate"
else
  bad "public-unit-no-regression:human-merge-gate"
fi

python3 -c "
import json, sys
data = json.load(open(sys.argv[1]))
ids = {e['id'] for e in data.get('fixtures', [])}
need = {'authoring-guard-fixtures', 'planning-currency-fixtures', 'visibility-fixtures'}
assert need <= ids
" "$ROOT/core/sw-reference/pr-test-plan.manifest.json" && ok "public-unit-no-regression:frozen-doc-gates" || bad "public-unit-no-regression:frozen-doc-gates"

# --- doc-impact-visibility-store (R23) ---
check_doc "$ROOT/.gitignore" gitignore \
  'visibility-generated' 'gitignore-generate' 'planning-materialized'

check_doc "$ROOT/core/skills/memory/SKILL.md" memory-skill \
  'docs/planning/' 'planning\.store' 'body-only|body only|body storage'

check_doc "$ROOT/core/providers/recallium.md" recallium \
  'docs/planning/' 'storage-only|storage only|body storage'

check_doc "$ROOT/core/rules/memory-guardrails.mdc" memory-guardrails \
  'planning\.store' 'memory-redact\.py'

check_doc "$ROOT/core/commands/sw-init.md" sw-init \
  'planning-init-seed' 'privacy' 'visibilityProfile|visibility profile'

check_doc "$ROOT/core/skills/deliver/SKILL.md" deliver-skill \
  'planning-materialized' 'materializ' 'commit-boundary|commit boundary' 'teardown'

for example in "$ROOT/core/sw-reference/workflow.config.example.json" "$ROOT/.sw/workflow.config.example.json"; do
  check_doc "$example" "workflow-example:$(basename "$(dirname "$example")")" \
    '"store"' '"backend"' 'visibilityProfile'
done

check_doc "$ROOT/core/sw-reference/config.schema.json" config-schema \
  'visibilityProfile' 'store'

check_doc "$ROOT/docs/guides/configuration.md" configuration \
  'planning\.store|planning\.visibilityProfile|visibilityProfile'

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
