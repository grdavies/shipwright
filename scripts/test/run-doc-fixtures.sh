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

if grep -q 'docs/decisions/<n>-<slug>.md' "$SW_DOC_REVIEW" && grep -q 'all seven' "$SW_DOC_REVIEW"; then
  echo "OK  sw-doc-review routes decision drafts to Full panel"
else
  echo "FAIL sw-doc-review decision draft routing"
  FAIL=1
fi

if grep -q 'Decision amendment review' "$DOC_REVIEW_SKILL" && \
   grep -q 'adversarial, feasibility' "$DOC_REVIEW_SKILL" && \
   grep -q 'docs/prds/<n>-<slug>/amendments' "$DOC_REVIEW_SKILL"; then
  echo "OK  doc-review skill: decision amendment raised floor + PRD amendment unchanged"
else
  echo "FAIL doc-review decision amendment floor"
  FAIL=1
fi

exit $FAIL
