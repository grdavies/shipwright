#!/usr/bin/env bash
# Fixture tests for spec-union.sh and check-frozen.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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
  mkdir -p prds/test
  cat > prds/test/frozen-prd.md <<'EOF'
---
frozen: true
---
# Frozen
EOF
  git add prds/test/frozen-prd.md
  git commit -m "add frozen" --quiet
  echo "edit" >> prds/test/frozen-prd.md
  git add prds/test/frozen-prd.md
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

exit $FAIL
