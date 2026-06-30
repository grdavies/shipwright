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
# Fixture tests for spec-union.sh and check-frozen.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
SRC_FIX="$ROOT/scripts/test/fixtures/spec-union"
UNION="$ROOT/scripts/spec-union.sh"
FROZEN="$ROOT/scripts/check-frozen.sh"
FAIL=0

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT
cp -R "$SRC_FIX/." "$FIX/"

# --- spec-union: add + supersede (A2 not present yet) ---
rm -f "$FIX/amendments/A2-retract.md"
OUT=$(bash "$UNION" "$FIX/parent-prd.md")
IDS=$(echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(','.join(r['id'] for r in d['requirements']))")
if echo "$IDS" | grep -q 'R1' && echo "$IDS" | grep -q 'R3' && echo "$IDS" | grep -q 'R4' && ! echo "$IDS" | grep -q 'R2'; then
  echo "OK  spec-union add+supersede"
else
  echo "FAIL spec-union expected R1,R3,R4 got $IDS"
  FAIL=1
fi

# --- spec-union: retract after supersede ---
cp "$SRC_FIX/amendments/A2-retract.md" "$FIX/amendments/A2-retract.md"
OUT2=$(bash "$UNION" "$FIX/parent-prd.md")
IDS2=$(echo "$OUT2" | python3 -c "import json,sys; d=json.load(sys.stdin); print(','.join(r['id'] for r in d['requirements']))")
if echo "$IDS2" | grep -q 'R3' && ! echo "$IDS2" | grep -q 'R1'; then
  echo "OK  spec-union retract"
else
  echo "FAIL spec-union retract got $IDS2"
  FAIL=1
fi

# --- check-frozen: clean tree pass ---
if bash "$FROZEN" HEAD 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
  echo "OK  check-frozen pass (no violations)"
else
  echo "FAIL check-frozen should pass on clean tree"
  FAIL=1
fi

# --- check-frozen: reject frozen modification ---
TMPGIT=$(mktemp -d)
trap 'rm -rf "$FIX" "$TMPGIT"' EXIT
git init -q "$TMPGIT"
(
  cd "$TMPGIT"
  git config user.email "test@example.com"
  git config user.name "Test"
  mkdir -p docs/prds/test
  cat > docs/prds/test/frozen-prd.md <<'EOF'
---
frozen: true
---
# Frozen
EOF
  git add docs/prds/test/frozen-prd.md
  git commit -m "add frozen" --quiet
  echo "edit" >> docs/prds/test/frozen-prd.md
  git add docs/prds/test/frozen-prd.md
  git commit -m "modify frozen" --quiet
  OUT=$(bash "$ROOT/scripts/check-frozen.sh" HEAD~1 2>/dev/null || true)
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='fail' else 1)"; then
    echo "OK  check-frozen rejects frozen modification"
  else
    echo "FAIL check-frozen should reject frozen modification"
    exit 1
  fi
) || FAIL=1

# --- check-frozen: allow pure doc-format normalization of a frozen artifact (PRD 033 A1) ---
TMPGIT_NORM=$(mktemp -d)
(
  cd "$TMPGIT_NORM"
  git init -q
  git config user.email "test@example.com"; git config user.name "Test"
  mkdir -p docs/prds/normtest
  cat > docs/prds/normtest/prd.md <<'EOF'
---
frozen: true
---
# Norm

## Decision Log

- **D1.** A decision
EOF
  git add -A && git commit -m "add frozen with D1. variant" --quiet
  python3 "$ROOT/scripts/doc_format.py" write --inplace docs/prds/normtest/prd.md
  git add -A && git commit -m "normalize decision log" --quiet
  OUT=$(bash "$ROOT/scripts/check-frozen.sh" HEAD~1 2>/dev/null || true)
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
    echo "OK  check-frozen allows pure doc-format normalization"
  else
    echo "FAIL check-frozen should allow pure doc-format normalization"
    FAIL=1
  fi
)
rm -rf "$TMPGIT_NORM"

# --- check-frozen: allow frozen task-list refresh bound to an added frozen amendment (PRD 033 A1) ---
TMPGIT_AMD=$(mktemp -d)
(
  cd "$TMPGIT_AMD"
  git init -q
  git config user.email "test@example.com"; git config user.name "Test"
  mkdir -p docs/prds/amdtest
  cat > docs/prds/amdtest/tasks-amdtest.md <<'EOF'
---
frozen: true
---
# Tasks

## Tasks

### 1. Phase one — S

- [ ] 1.1 Do a thing (R1)
EOF
  git add -A && git commit -m "add frozen task list" --quiet
  mkdir -p docs/prds/amdtest/amendments
  cat > docs/prds/amdtest/amendments/A1.md <<'EOF'
---
amends: docs/prds/amdtest/tasks-amdtest.md
frozen: true
---
# Amendment A1
EOF
  printf '\n### 2. Phase two — S\n\n- [ ] 2.1 New thing (R2)\n' >> docs/prds/amdtest/tasks-amdtest.md
  git add -A && git commit -m "refresh task list + add amendment" --quiet
  OUT=$(bash "$ROOT/scripts/check-frozen.sh" HEAD~1 2>/dev/null || true)
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
    echo "OK  check-frozen allows amendment-companion task-list refresh"
  else
    echo "FAIL check-frozen should allow amendment-companion task-list refresh"
    FAIL=1
  fi
)
rm -rf "$TMPGIT_AMD"

# --- check-frozen: still reject a frozen task-list change with no companion amendment ---
TMPGIT_NEG=$(mktemp -d)
(
  cd "$TMPGIT_NEG"
  git init -q
  git config user.email "test@example.com"; git config user.name "Test"
  mkdir -p docs/prds/negtest
  cat > docs/prds/negtest/tasks-negtest.md <<'EOF'
---
frozen: true
---
# Tasks

## Tasks

### 1. Phase one — S

- [ ] 1.1 Do a thing (R1)
EOF
  git add -A && git commit -m "add frozen task list" --quiet
  printf '\n### 2. Phase two — S\n\n- [ ] 2.1 New thing (R2)\n' >> docs/prds/negtest/tasks-negtest.md
  git add -A && git commit -m "refresh task list without amendment" --quiet
  OUT=$(bash "$ROOT/scripts/check-frozen.sh" HEAD~1 2>/dev/null || true)
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='fail' else 1)"; then
    echo "OK  check-frozen rejects frozen task-list change without amendment"
  else
    echo "FAIL check-frozen should reject frozen task-list change without amendment"
    FAIL=1
  fi
)
rm -rf "$TMPGIT_NEG"

# --- spec-union: ## R<n> heading format (exemplar shape) ---
FIX3=$(mktemp -d)
cp "$FIX/parent-prd.md" "$FIX3/"
mkdir -p "$FIX3/amendments"
rm -f "$FIX3/amendments/"*
cat > "$FIX3/amendments/A1-heading.md" <<'EOF'
---
supersedes: [R2]
---
## R5 (supersedes R2)
Replacement requirement text.
EOF
OUT3=$(bash "$UNION" "$FIX3/parent-prd.md")
if echo "$OUT3" | python3 -c "import json,sys; d=json.load(sys.stdin); ids=[r['id'] for r in d['requirements']]; assert 'R5' in ids and 'R2' not in ids and d['superseded'].get('R2')=='R5'"; then
  echo "OK  spec-union heading format"
else
  echo "FAIL spec-union heading format"
  FAIL=1
fi

# --- spec-union: numeric amendment order (A2 before A10) ---
FIX4=$(mktemp -d)
cat > "$FIX4/parent-prd.md" <<'EOF'
---
frozen: true
---
# Parent
- **R1** First
- **R2** Second
EOF
mkdir -p "$FIX4/amendments"
cat > "$FIX4/amendments/A10-later.md" <<'EOF'
---
retracts: [R1]
---
# Later retract
EOF
cat > "$FIX4/amendments/A2-earlier.md" <<'EOF'
---
---
# Earlier add
- **R3** Third
EOF
OUT4=$(bash "$UNION" "$FIX4/parent-prd.md")
if echo "$OUT4" | python3 -c "import json,sys; d=json.load(sys.stdin); ids=[r['id'] for r in d['requirements']]; assert 'R3' in ids and 'R1' not in ids and 'R2' in ids"; then
  echo "OK  spec-union numeric amendment order"
else
  echo "FAIL spec-union numeric amendment order got $(echo "$OUT4" | python3 -c 'import json,sys; print([r["id"] for r in json.load(sys.stdin)["requirements"]])')"
  FAIL=1
fi

# --- spec-rigor: decision record pass ---
SPEC_RIGOR_CHECK="$ROOT/scripts/spec-rigor-check.sh"
FIX_DECISION="$ROOT/scripts/test/fixtures"
SW_FREEZE="$(content_path commands/sw-freeze.md)"
SW_PRD="$(content_path commands/sw-prd.md)"

set +e
OUT_DEC=$(bash "$SPEC_RIGOR_CHECK" --artifact decision --path "$FIX_DECISION/decision-record-pass.md" --tier full 2>/dev/null)
EC_DEC=$?
set -e
if [[ "$EC_DEC" -eq 0 ]] && echo "$OUT_DEC" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' and d.get('artifact')=='decision' else 1)"; then
  echo "OK  spec-rigor-check: decision record → pass"
else
  echo "FAIL spec-rigor-check decision pass case (ec=$EC_DEC)"
  FAIL=1
fi

set +e
OUT_DEC_FAIL=$(bash "$SPEC_RIGOR_CHECK" --artifact decision --path "$FIX_DECISION/decision-record-fail.md" --tier full 2>/dev/null)
EC_DEC_FAIL=$?
set -e
if [[ "$EC_DEC_FAIL" -eq 20 ]] && echo "$OUT_DEC_FAIL" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='fail' else 1)"; then
  echo "OK  spec-rigor-check: incomplete decision → fail"
else
  echo "FAIL spec-rigor-check decision fail case (ec=$EC_DEC_FAIL)"
  FAIL=1
fi

# --- spec-rigor: tasks Phase Dependencies (R5/R6/R37) ---
FIX_TASKS_PD="$ROOT/scripts/test/fixtures/tasks-phase-deps"
SW_TASKS="$(content_path commands/sw-tasks.md)"
TASKS_SKILL="$(content_path skills/tasks/SKILL.md)"

set +e
OUT_TASKS_PD=$(bash "$SPEC_RIGOR_CHECK" --artifact tasks \
  --path "$FIX_TASKS_PD/pass.md" \
  --prd "$FIX_TASKS_PD/parent-prd.md" 2>/dev/null)
EC_TASKS_PD=$?
set -e
if [[ "$EC_TASKS_PD" -eq 0 ]] && echo "$OUT_TASKS_PD" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('verdict')=='pass' else 1)"; then
  echo "OK  spec-rigor-check: tasks with Phase Dependencies → pass"
else
  echo "FAIL spec-rigor-check tasks phase-deps pass (ec=$EC_TASKS_PD)"
  FAIL=1
fi

set +e
OUT_TASKS_PD_FAIL=$(bash "$SPEC_RIGOR_CHECK" --artifact tasks \
  --path "$FIX_TASKS_PD/fail-missing.md" \
  --prd "$FIX_TASKS_PD/parent-prd.md" 2>/dev/null)
EC_TASKS_PD_FAIL=$?
set -e
if [[ "$EC_TASKS_PD_FAIL" -eq 20 ]] && echo "$OUT_TASKS_PD_FAIL" | python3 -c "
import json,sys
d=json.load(sys.stdin)
msgs=' '.join(f['message'] for f in d.get('findings',[]))
sys.exit(0 if 'Phase Dependencies' in msgs else 1)
"; then
  echo "OK  spec-rigor-check: tasks missing Phase Dependencies → fail"
else
  echo "FAIL spec-rigor-check tasks phase-deps fail (ec=$EC_TASKS_PD_FAIL)"
  FAIL=1
fi

if grep -q '## Phase Dependencies' "$SW_TASKS" && grep -q '| Phase | Depends on |' "$SW_TASKS"; then
  echo "OK  sw-tasks documents Phase Dependencies emission"
else
  echo "FAIL sw-tasks missing Phase Dependencies contract"
  FAIL=1
fi

if grep -q '## Phase Dependencies' "$TASKS_SKILL" && \
   grep -q 'Sequential fallback (R8)' "$TASKS_SKILL" && \
   grep -qi 'sequential fallback' "$TASKS_SKILL"; then
  echo "OK  tasks skill documents Phase Dependencies + R8 fallback"
else
  echo "FAIL tasks skill missing Phase Dependencies / R8 docs"
  FAIL=1
fi

# --- U1: sw-prd --type decision + sw-freeze routing ---
if grep -q '\-\-type decision' "$SW_PRD" && grep -q 'docs/decisions/<n>-<slug>.md' "$SW_PRD"; then
  echo "OK  sw-prd documents --type decision path"
else
  echo "FAIL sw-prd missing --type decision contract"
  FAIL=1
fi

if grep -q '\-\-artifact decision' "$SW_FREEZE" && grep -q 'docs/decisions/INDEX.md' "$SW_FREEZE" && \
   grep -q 'No task list generation' "$SW_FREEZE"; then
  echo "OK  sw-freeze routes decision rigor + INDEX (no tasks)"
else
  echo "FAIL sw-freeze decision freeze contract"
  FAIL=1
fi

if [[ -f "$ROOT/docs/decisions/INDEX.md" ]] && ! grep -q 'frozen: true' "$ROOT/docs/decisions/INDEX.md"; then
  echo "OK  docs/decisions/INDEX.md exists (living, not frozen)"
else
  echo "FAIL docs/decisions/INDEX.md missing or frozen"
  FAIL=1
fi

if grep -q 'docs/decisions/' "$ROOT/.sw/layout.md" && grep -q 'Decision record numbering' "$ROOT/.sw/layout.md"; then
  echo "OK  .sw/layout.md documents docs/decisions/ tree"
else
  echo "FAIL .sw/layout.md missing docs/decisions/ contract"
  FAIL=1
fi

# --- U3: decision record-level supersede + sibling amend dir ---
DECISION_PARENT="$ROOT/scripts/test/fixtures/spec-union/parent-decision.md"
OUT_DEC_UNION=$(bash "$UNION" "$DECISION_PARENT")
if echo "$OUT_DEC_UNION" | python3 -c "
import json,sys
d=json.load(sys.stdin)
ids=[r['id'] for r in d['requirements']]
assert 'D1' not in ids and 'D2' in ids
assert d['superseded'].get('D1',{}).get('replacement','').endswith('replacement-decision.md')
"; then
  echo "OK  spec-union decision record-level supersede"
else
  echo "FAIL spec-union decision record-level supersede"
  FAIL=1
fi

# --- U3: PRD path byte-identical regression (golden shape) ---
OUT_PRD_GOLDEN=$(bash "$UNION" "$FIX/parent-prd.md")
if echo "$OUT_PRD_GOLDEN" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert all(isinstance(v,str) for v in d.get('superseded',{}).values())
assert 'replacement' not in json.dumps(d)
"; then
  echo "OK  spec-union PRD superseded map unchanged (string values only)"
else
  echo "FAIL spec-union PRD regression shape"
  FAIL=1
fi

# --- U2: decision-record doc-review routing ---
SW_DOC_REVIEW="$(content_path commands/sw-doc-review.md)"
DOC_REVIEW_SKILL="$(content_path skills/doc-review/SKILL.md)"

if grep -q 'docs/decisions/<n>-<slug>.md' "$SW_DOC_REVIEW" && grep -q 'all eight' "$SW_DOC_REVIEW"; then
  echo "OK  sw-doc-review routes decision drafts to Full panel"
else
  echo "FAIL sw-doc-review decision draft routing"
  FAIL=1
fi

if grep -q 'Decision amendment review' "$DOC_REVIEW_SKILL" && \
   grep -q 'adversarial, feasibility' "$DOC_REVIEW_SKILL" && \
   grep -q 'docs-currency' "$DOC_REVIEW_SKILL" && \
   grep -q 'docs/prds/<n>-<slug>/amendments' "$DOC_REVIEW_SKILL"; then
  echo "OK  doc-review skill: decision amendment raised floor + PRD amendment includes docs-currency"
else
  echo "FAIL doc-review decision amendment floor"
  FAIL=1
fi

# --- doc.afterTasks → /sw-deliver run + frozen-spec seed (PRD 005 A1/A2) ---
DOC_AFTER="$ROOT/scripts/test/fixtures"
for fx in \
  doc-afterTasks-stop-deliver \
  doc-afterTasks-confirm-deliver \
  doc-afterTasks-auto-deliver \
  doc-afterTasks-guides-deliver \
  doc-afterTasks-seed-confirm-auto \
  doc-afterTasks-seed-stop \
  doc-afterTasks-seed-branch-derivation \
  doc-afterTasks-seed-brainstorm-excluded; do
  bash "$DOC_AFTER/${fx}.sh" || FAIL=1
done

# --- PRD 006: communication routing ---
bash "$ROOT/scripts/test/fixtures/communication-routing.sh" || FAIL=1

# --- PRD 020: docs-currency review persona ---
DOCS_CURRENCY_AGENT="$(content_path agents/sw-docs-currency-reviewer.md)"
SYNTHESIS_REF="$(content_path skills/doc-review/references/synthesis.md)"
MODEL_DEFAULTS="$ROOT/core/sw-reference/model-routing.defaults.json"
WORKFLOW_CONFIG="$ROOT/.cursor/workflow.config.json"

if [[ -f "$DOCS_CURRENCY_AGENT" ]] && \
   grep -q 'sw-docs-currency-reviewer' "$DOCS_CURRENCY_AGENT" && \
   grep -qi 'which in-repo documentation artifacts are affected' "$DOCS_CURRENCY_AGENT" && \
   grep -q 'findings-schema.json' "$DOCS_CURRENCY_AGENT" && \
   grep -qi 'no affected artifacts' "$DOCS_CURRENCY_AGENT" && \
   grep -q 'README.md' "$DOCS_CURRENCY_AGENT" && \
   grep -q 'core/commands/' "$DOCS_CURRENCY_AGENT" && \
   grep -q 'core/skills/' "$DOCS_CURRENCY_AGENT"; then
  echo "OK  docs-currency-persona-present"
else
  echo "FAIL docs-currency-persona-present"
  FAIL=1
fi

if grep -q 'sw-docs-currency-reviewer' "$DOC_REVIEW_SKILL" && \
   grep -qi 'always-on core' "$DOC_REVIEW_SKILL" && \
   grep -q 'docs-currency' "$DOC_REVIEW_SKILL" && \
   grep -qi 'activation record' "$DOC_REVIEW_SKILL"; then
  echo "OK  docs-currency-always-on-core"
else
  echo "FAIL docs-currency-always-on-core"
  FAIL=1
fi

if grep -q 'coherence' "$DOC_REVIEW_SKILL" && \
   grep -q 'scope-guardian' "$DOC_REVIEW_SKILL" && \
   grep -q 'docs-currency' "$DOC_REVIEW_SKILL" && \
   grep -q 'Amendment review (U7)' "$DOC_REVIEW_SKILL" && \
   grep -q 'Decision amendment review' "$DOC_REVIEW_SKILL" && \
   grep -q 'Quick' "$DOC_REVIEW_SKILL"; then
  echo "OK  docs-currency-amendment-floor"
else
  echo "FAIL docs-currency-amendment-floor"
  FAIL=1
fi

if grep -qi 'Doc-surface taxonomy' "$DOCS_CURRENCY_AGENT" && \
   grep -q 'no affected artifacts' "$DOCS_CURRENCY_AGENT" && \
   grep -q 'path' "$DOCS_CURRENCY_AGENT"; then
  echo "OK  docs-currency-artifact-mapping"
else
  echo "FAIL docs-currency-artifact-mapping"
  FAIL=1
fi

if grep -qi 'docs-currency findings' "$SYNTHESIS_REF" && \
   grep -q 'gated_auto' "$SYNTHESIS_REF" && \
   grep -q 'manual' "$SYNTHESIS_REF" && \
   grep -qi 'never a hard freeze' "$SYNTHESIS_REF"; then
  echo "OK  docs-currency-output-folds-to-spec"
else
  echo "FAIL docs-currency-output-folds-to-spec"
  FAIL=1
fi

if grep -q 'INDEX.md' "$DOC_REVIEW_SKILL" && \
   grep -q 'COMPLETION-LOG.md' "$DOC_REVIEW_SKILL" && \
   grep -q 'GAP-BACKLOG.md' "$DOC_REVIEW_SKILL" && \
   grep -qi 'Living-doc complementarity' "$DOC_REVIEW_SKILL" && \
   grep -qi 'must not re-gate' "$DOC_REVIEW_SKILL"; then
  echo "OK  docs-currency-no-living-doc-overlap"
else
  echo "FAIL docs-currency-no-living-doc-overlap"
  FAIL=1
fi

if grep -q '"sw-docs-currency-reviewer": "build"' "$WORKFLOW_CONFIG" && \
   grep -q '"sw-docs-currency-reviewer": "build"' "$MODEL_DEFAULTS" && \
   grep -q 'dispatch-check' "$DOC_REVIEW_SKILL"; then
  echo "OK  docs-currency-tier-build"
else
  echo "FAIL docs-currency-tier-build"
  FAIL=1
fi

if [[ -f "$ROOT/dist/cursor/agents/sw-docs-currency-reviewer.md" ]] && \
   [[ -f "$ROOT/dist/claude-code/agents/sw-docs-currency-reviewer.md" ]]; then
  echo "OK  docs-currency-emitter-freshness"
else
  echo "FAIL docs-currency-emitter-freshness"
  FAIL=1
fi

if grep -q 'sw-docs-currency-reviewer' "$DOC_REVIEW_SKILL" && \
   grep -q 'docs-currency' "$SW_DOC_REVIEW" && \
   grep -qi 'Living-doc complementarity' "$DOC_REVIEW_SKILL"; then
  echo "OK  docs-currency-docs-presence"
else
  echo "FAIL docs-currency-docs-presence"
  FAIL=1
fi

# --- PRD 009 A2: user docs presence (R56–R57) ---
bash "$ROOT/scripts/docs-presence-check.sh" || FAIL=1

exit $FAIL

"""

if __name__ == "__main__":
    raise SystemExit(main())
