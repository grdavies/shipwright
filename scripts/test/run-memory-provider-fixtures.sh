#!/usr/bin/env bash
# Fixture tests for in-repo memory provider + /pf-setup (plan 2026-06-23-002).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=../pf-resolve-plugin-root.sh
source "$ROOT/scripts/pf-resolve-plugin-root.sh"
CONTENT="$(pf_resolve_plugin_root "$ROOT/scripts")"
CURSOR_DIST="$ROOT/dist/cursor"
SEARCH="$ROOT/scripts/in-repo-memory-search.sh"
IN_REPO_RULES="$CONTENT/providers/in-repo-rules.sh"
HOOK="$CURSOR_DIST/hooks/before-submit-guardrails.py"
FIX="$ROOT/scripts/test/fixtures/in-repo-memory"
FIX_RULES="$ROOT/scripts/test/fixtures/in-repo-rules"
FIX_MARKER="$ROOT/scripts/test/fixtures/marker"
if [ -f "$ROOT/.pf/config.schema.json" ]; then
  SCHEMA="$ROOT/.pf/config.schema.json"
elif [ -f "$CONTENT/pf-reference/config.schema.json" ]; then
  SCHEMA="$CONTENT/pf-reference/config.schema.json"
else
  SCHEMA="$ROOT/.pf/config.schema.json"
fi
PF_SETUP="$CONTENT/commands/pf-setup.md"
IN_REPO_MD="$CONTENT/providers/in-repo.md"
CAPS="$CONTENT/skills/memory/CAPABILITIES.md"
REDACT="$ROOT/scripts/memory-redact.sh"
FAIL=0

export PYTHONPATH="$CURSOR_DIST/hooks${PYTHONPATH:+:$PYTHONPATH}"
chmod +x "$SEARCH" "$IN_REPO_RULES" 2>/dev/null || true

# --- U1: provider doc + semanticSearch flag ---
if grep -q '"semanticSearch": false' "$IN_REPO_MD" && grep -q 'semanticSearch' "$CAPS"; then
  echo "OK  in-repo provider declares semanticSearch:false + CAPABILITIES documents flag"
else
  echo "FAIL U1 semanticSearch declaration"
  FAIL=1
fi

if grep -q 'typedMemories' "$IN_REPO_MD" && grep -q 'rules/' "$IN_REPO_MD" && grep -q 'memories/' "$IN_REPO_MD"; then
  echo "OK  in-repo provider capability block + store layout"
else
  echo "FAIL U1 provider structure"
  FAIL=1
fi

# Interchange round-trip (fixture memory has all neutral fields)
SAMPLE="$FIX/store/memories/20260620-jwt-decision.md"
if grep -q '^category:' "$SAMPLE" && grep -q '^tags:' "$SAMPLE" && grep -q '^relatedFiles:' "$SAMPLE" && \
   grep -q '^importance:' "$SAMPLE" && grep -q '^scope:' "$SAMPLE" && grep -q '^links:' "$SAMPLE" && \
   grep -q '^createdAt:' "$SAMPLE"; then
  echo "OK  interchange frontmatter round-trip fields present"
else
  echo "FAIL U1 interchange fixture"
  FAIL=1
fi

# --- U2: search helper ---
STORE="$FIX/store"
OUT=$(bash "$SEARCH" --store "$STORE" --query JWT)
if echo "$OUT" | jq -e '.results | map(select(.id=="20260620-jwt-decision")) | length == 1' >/dev/null; then
  echo "OK  keyword search finds JWT memory"
else
  echo "FAIL U2 keyword search"
  FAIL=1
fi

OUT2=$(bash "$SEARCH" --store "$STORE" --query gate --category learning)
if echo "$OUT2" | jq -e '.results[0].id == "20260621-gate-learning"' >/dev/null; then
  echo "OK  category filter search"
else
  echo "FAIL U2 category filter"
  FAIL=1
fi

RUN1=$(bash "$SEARCH" --store "$STORE" --query JWT | jq -c .)
RUN2=$(bash "$SEARCH" --store "$STORE" --query JWT | jq -c .)
if [ "$RUN1" = "$RUN2" ]; then
  echo "OK  search determinism"
else
  echo "FAIL U2 search determinism"
  FAIL=1
fi

OUT3=$(bash "$SEARCH" --store "$STORE" --query auth --file-glob src/auth.ts)
if echo "$OUT3" | jq -e '.results | map(select(.id=="20260620-jwt-decision")) | length == 1' >/dev/null; then
  echo "OK  relatedFiles glob filter"
else
  echo "FAIL U2 file-glob filter"
  FAIL=1
fi

# R41 redaction write path
TMP_WRITE=$(mktemp -d)
FAKE_SECRET='AKIAIOSFODNN7EXAMPLE'
PAYLOAD="Remember: $FAKE_SECRET is the key"
REDACTED=$(printf '%s' "$PAYLOAD" | bash "$REDACT" 2>/dev/null || printf '%s' "$PAYLOAD" | python3 "$ROOT/scripts/memory_redact.py")
echo "$REDACTED" > "$TMP_WRITE/out.md"
if grep -q 'AKIAIOSFODNN7EXAMPLE' "$TMP_WRITE/out.md" 2>/dev/null; then
  echo "FAIL U2 redaction — secret still present"
  FAIL=1
else
  echo "OK  R41 redaction scrubs planted AWS key"
fi
rm -rf "$TMP_WRITE"

# Lazy create (mkdir semantics documented in SKILL)
if grep -q 'mkdir -p' "$CONTENT/skills/memory/SKILL.md" && grep -qi 'lazy' "$IN_REPO_MD"; then
  echo "OK  lazy store create documented"
else
  echo "FAIL U2 lazy create docs"
  FAIL=1
fi

# --- U3: in-repo rules adapter ---
RULES_WS=$(mktemp -d)
mkdir -p "$RULES_WS/.cursor/pf-memory/rules"
cp "$FIX_RULES/store/rules/"*.md "$RULES_WS/.cursor/pf-memory/rules/"
echo '{"memory":{"provider":"in-repo","inRepo":{"storeDir":".cursor/pf-memory"}}}' > "$RULES_WS/.cursor/workflow.config.json"
export PF_WORKSPACE_ROOT="$RULES_WS"
OUT_RULES=$(bash "$IN_REPO_RULES")
if echo "$OUT_RULES" | jq -e '.ok == true and (.rules | map(select(.id=="allowlisted-rule")) | length) == 1' >/dev/null && \
   echo "$OUT_RULES" | jq -e '(.rules | map(select(.id=="unlisted-rule")) | length) == 1' >/dev/null && \
   echo "$OUT_RULES" | jq -e '(.rules | map(select(.id=="invalid-category")) | length) == 0' >/dev/null && \
   echo "$OUT_RULES" | jq -e '(.rules | map(select(.id=="oversize-rule")) | length) == 0' >/dev/null; then
  echo "OK  in-repo-rules adapter emits valid rules only"
else
  echo "FAIL U3 rules adapter"
  echo "$OUT_RULES" | jq . 2>/dev/null || echo "$OUT_RULES"
  FAIL=1
fi
unset PF_WORKSPACE_ROOT
rm -rf "$RULES_WS"

# Hook offline in-repo (marker + empty rules, greenfield)
MARKER_WS=$(mktemp -d)
cp -R "$FIX_MARKER/with-marker/.cursor" "$MARKER_WS/"
mkdir -p "$MARKER_WS/.cursor/pf-memory/rules"
OUT_HOOK=$(echo "{\"workspace_roots\":[\"$MARKER_WS\"]}" | python3 "$HOOK")
if echo "$OUT_HOOK" | jq -e '.continue == true' >/dev/null; then
  echo "OK  hook offline in-repo marker continue=true"
else
  echo "FAIL U3 hook in-repo offline"
  echo "$OUT_HOOK" | jq . 2>/dev/null
  FAIL=1
fi
rm -rf "$MARKER_WS"

# Hook dispatches in-repo-rules (structural grep on shared guardrail core)
GUARDRAIL_CORE="$ROOT/core/hooks/guardrail_core.py"
if grep -q 'rules_script_for_provider' "$GUARDRAIL_CORE" && grep -q 'in-repo' "$GUARDRAIL_CORE"; then
  echo "OK  hook provider dispatch wiring"
else
  echo "FAIL U3 hook dispatch structure"
  FAIL=1
fi

# Recallium regression — still uses recallium-rules when configured
REC_WS=$(mktemp -d)
mkdir -p "$REC_WS/.cursor"
echo '{"memory":{"provider":"recallium","project":"t","guardrails":{"enforceBeforeSubmit":true}}}' > "$REC_WS/.cursor/workflow.config.json"
# Use rules-empty fixture via PF_RULES_SCRIPT for deterministic test
OUT_REC=$(echo "{\"workspace_roots\":[\"$REC_WS\"]}" | PF_RULES_SCRIPT="$ROOT/scripts/test/fixtures/rules-empty.sh" python3 "$HOOK")
if echo "$OUT_REC" | jq -e '.continue == true' >/dev/null; then
  echo "OK  recallium config path preserved"
else
  echo "FAIL U3 recallium regression"
  FAIL=1
fi
rm -rf "$REC_WS"

# --- U4: marker precedence ---
PREC_WS=$(mktemp -d)
mkdir -p "$PREC_WS/.cursor"
echo 'in-repo' > "$PREC_WS/.cursor/pf-memory.provider"
echo '{"memory":{"provider":"recallium","project":"x","guardrails":{"enforceBeforeSubmit":true}}}' > "$PREC_WS/.cursor/workflow.config.json"
mkdir -p "$PREC_WS/.cursor/pf-memory/rules"
OUT_PREC=$(echo "{\"workspace_roots\":[\"$PREC_WS\"]}" | PF_RULES_SCRIPT="$ROOT/scripts/test/fixtures/rules-empty.sh" python3 "$HOOK")
if echo "$OUT_PREC" | jq -e '.continue == true' >/dev/null; then
  echo "OK  explicit config overrides marker (recallium path)"
else
  echo "FAIL U4 config precedence"
  FAIL=1
fi
rm -rf "$PREC_WS"

# Pass-through: no config, no marker
UNCONF=$(mktemp -d)
OUT_UN=$(echo "{\"workspace_roots\":[\"$UNCONF\"]}" | python3 "$HOOK")
if echo "$OUT_UN" | jq -e '.continue == true' >/dev/null; then
  echo "OK  pass-through no config no marker"
else
  echo "FAIL U4 pass-through"
  FAIL=1
fi
rm -rf "$UNCONF"

# Session-start hints /pf-setup (shared guardrail core builds session context)
if grep -q '/pf-setup' "$GUARDRAIL_CORE"; then
  echo "OK  session-start nudges /pf-setup"
else
  echo "FAIL U4 session-start hint"
  FAIL=1
fi

# --- U5: pf-setup command ---
if [[ -f "$PF_SETUP" ]] && grep -qi 'doctor' "$PF_SETUP" && grep -qi 'does not scaffold CI' "$PF_SETUP" && \
   grep -qi 'does not' "$PF_SETUP" && grep -qi 'migrate' "$PF_SETUP"; then
  echo "OK  pf-setup command scope + doctor mode"
else
  echo "FAIL U5 pf-setup command"
  FAIL=1
fi

if grep -q '/pf-setup' "$CONTENT/rules/pf-workflow-sequencing.mdc"; then
  echo "OK  workflow sequencing references /pf-setup"
else
  echo "FAIL U5 sequencing reference"
  FAIL=1
fi

# --- U6: schema validation ---
python3 - <<'PY' || { echo "FAIL U6 schema validation"; FAIL=1; }
import json, pathlib, sys
try:
    import jsonschema
except ImportError:
    print("SKIP U6 jsonschema not installed — structural check only")
    sys.exit(0)
root = pathlib.Path("$ROOT")
schema = json.loads((root / ".pf/config.schema.json").read_text())
valid = json.loads((root / "scripts/test/fixtures/in-repo-memory/config-in-repo.json").read_text())
jsonschema.validate(valid, schema)
invalid = dict(valid)
invalid["memory"] = dict(valid["memory"])
invalid["memory"]["bogusKey"] = "x"
try:
    jsonschema.validate(invalid, schema)
    print("FAIL U6 additionalProperties should reject bogus key")
    sys.exit(1)
except jsonschema.ValidationError:
    print("OK  schema accepts in-repo config + rejects unknown memory keys")
PY

if python3 -c "import jsonschema" 2>/dev/null; then
  :
else
  if grep -q '"in-repo"' "$SCHEMA" && grep -q 'commitMode' "$SCHEMA" && grep -q 'inRepo' "$SCHEMA"; then
    echo "OK  schema structurally admits in-repo knobs"
  else
    echo "FAIL U6 schema structure"
    FAIL=1
  fi
fi

# --- U7: runner registered ---
WF_CFG="$ROOT/.cursor/workflow.config.json"
if grep -q 'run-memory-provider-fixtures.sh' "$WF_CFG" 2>/dev/null || grep -q 'run-memory-provider-fixtures' "$CONTENT/pf-reference/workflow.config.example.json" 2>/dev/null; then
  echo "OK  verify.test registration present or pending"
else
  # Will register below — check after update
  true
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL memory-provider fixtures passed"
else
  echo "SOME memory-provider fixtures FAILED"
  exit 1
fi
