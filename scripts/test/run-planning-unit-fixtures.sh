#!/usr/bin/env bash
# Planning-unit schema + validator fixtures (PRD 031 phase 3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SCHEMA="$ROOT/core/sw-reference/planning-unit.schema.json"
LAYOUT="$ROOT/core/sw-reference/layout.md"
ENUM="$ROOT/scripts/planning_status_enum.py"
VALIDATOR="$ROOT/scripts/planning-unit-validate.sh"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-unit"

# --- schema-fields-and-type-enum (R1) ---
if [[ -f "$SCHEMA" ]] && \
   python3 - "$SCHEMA" <<'PY'
import json, sys
schema = json.load(open(sys.argv[1]))
props = schema.get("properties", {})
required = {"id", "type", "status", "title", "visibility", "depends", "blocks",
            "supersedes", "extends", "absorbs", "priority", "tags"}
missing = required - set(props)
if missing:
    raise SystemExit(f"missing properties: {missing}")
types = set(props["type"]["enum"])
expected = {"brainstorm", "gap", "prd", "decision", "amendment"}
if types != expected:
    raise SystemExit(f"type enum mismatch: {types}")
if schema.get("additionalProperties") is not False:
    raise SystemExit("additionalProperties must be false")
print("ok")
PY
then
  ok "schema-fields-and-type-enum"
else
  bad "schema-fields-and-type-enum"
fi

# --- unit-folder-and-id-stability (R2) ---
if grep -q 'Unit folder layout' "$LAYOUT" && \
   grep -q 'never reused' "$LAYOUT" && \
   grep -q 'unit id' "$LAYOUT" && \
   grep -q 'amendments/' "$LAYOUT"; then
  ok "unit-folder-and-id-stability"
else
  bad "unit-folder-and-id-stability"
fi

# --- gap-unit-in-unified-index (R3) ---
if grep -q 'type: gap' "$LAYOUT" && \
   grep -q 'single generated unified INDEX' "$LAYOUT" && \
   grep -q 'not a separate gap-only' "$LAYOUT"; then
  ok "gap-unit-in-unified-index"
else
  bad "gap-unit-in-unified-index"
fi

# --- status-type-conditioned (R4) ---
if python3 - "$ENUM" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("pse", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.validate_status("gap", "open") is None
assert mod.validate_status("gap", "planned") is None
assert mod.validate_status("prd", "planned") is None
assert mod.validate_status("prd", "proposed") is None
assert "homonym" in mod.PLANNED_HOMONYM_NOTE
print("ok")
PY
then
  ok "status-type-conditioned"
else
  bad "status-type-conditioned"
fi

# --- cross-enum-token-rejected (R4) ---
if python3 - "$ENUM" <<'PY'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("pse", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
assert mod.validate_status("gap", "in-progress") is not None
assert mod.validate_status("prd", "open") is not None
print("ok")
PY
then
  ok "cross-enum-token-rejected"
else
  bad "cross-enum-token-rejected"
fi

# --- status-enum-stub (R4) ---
if python3 - "$ENUM" <<'PY'
import importlib.util, inspect, sys
spec = importlib.util.spec_from_file_location("pse", sys.argv[1])
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
src = inspect.getsource(mod)
assert "transition" in src.lower()
assert len(mod.GAP_STATUSES) == 4
assert len(mod.LIFECYCLE_STATUSES) == 8
print("ok")
PY
then
  ok "status-enum-stub"
else
  bad "status-enum-stub"
fi

# --- validate-unknown-key (R19) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp "$FIX_SRC/unknown-key.md" "$TMP/unknown-key.md"
if OUT=$(bash "$VALIDATOR" --path "$TMP/unknown-key.md" --repo-root "$ROOT" 2>/dev/null || true) && \
   echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'; assert any('unknown key' in e for e in d.get('errors',[]))"; then
  ok "validate-unknown-key"
else
  bad "validate-unknown-key"
fi

# --- validate-tracked-private-rejected (R19) ---
PRIV_FIX=$(mktemp -d)
GIT_FIX=$(mktemp -d)
trap 'rm -rf "$TMP" "$PRIV_FIX" "$GIT_FIX"' EXIT
cp "$FIX_SRC/private-tracked.md" "$PRIV_FIX/private.md"
(
  cd "$GIT_FIX"
  git init -q
  git config user.email "test@example.com"
  git config user.name "Test"
  mkdir -p docs/planning/brainstorm/brainstorm-001-private
  cp "$PRIV_FIX/private.md" docs/planning/brainstorm/brainstorm-001-private/body.md
  git add docs/planning/brainstorm/brainstorm-001-private/body.md
  git commit -m "add private unit" --quiet
  OUT=$(bash "$VALIDATOR" --path docs/planning/brainstorm/brainstorm-001-private/body.md --repo-root "$GIT_FIX" 2>/dev/null || true)
  python3 -c "import json,sys; d=json.loads(sys.argv[1]); assert d.get('verdict')=='fail'; assert any('git-tracked' in e for e in d.get('errors',[]))" "$OUT"
) && ok "validate-tracked-private-rejected" || bad "validate-tracked-private-rejected"

# --- validator passes valid units ---
if bash "$VALIDATOR" --path "$FIX_SRC/valid-prd.md" --repo-root "$ROOT" 2>/dev/null | \
   python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'" && \
   bash "$VALIDATOR" --path "$FIX_SRC/valid-gap.md" --repo-root "$ROOT" 2>/dev/null | \
   python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='pass'"; then
  ok "validate-valid-units-pass"
else
  bad "validate-valid-units-pass"
fi

# --- cross-enum via validator ---
cp "$FIX_SRC/cross-enum.md" "$TMP/cross-enum.md"
if OUT=$(bash "$VALIDATOR" --path "$TMP/cross-enum.md" --repo-root "$ROOT" 2>/dev/null || true) && echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail'; assert any('cross-enum' in e for e in d.get('errors',[]))"; then
  ok "validate-cross-enum-rejected"
else
  bad "validate-cross-enum-rejected"
fi

exit "$FAIL"
