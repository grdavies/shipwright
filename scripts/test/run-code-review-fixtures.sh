#!/usr/bin/env bash
# Fixture tests for local code-review loop (plan 2026-06-23-003).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
NORMALIZE="$ROOT/scripts/code-review-normalize.sh"
GATE="$ROOT/scripts/code-review-gate.sh"
APPLY_CHECK="$ROOT/scripts/code-review-apply-check.sh"
FIX="$ROOT/scripts/test/fixtures/code-review"
SCHEMA="$ROOT/.sw/config.schema.json"
SW_REVIEW="$(content_path commands/sw-review.md)"
SW_SHIP="$(content_path commands/sw-ship.md)"
CODE_REVIEW_RULES="$(content_path rules/code-review-automation.mdc)"
SEQUENCING="$(content_path rules/sw-workflow-sequencing.mdc)"
CE_ADAPTER="$(content_path providers/code-review/ce-code-review.md)"
CAPS="$(content_path providers/code-review/CAPABILITIES.md)"
FAIL=0

chmod +x "$NORMALIZE" "$GATE" "$APPLY_CHECK" 2>/dev/null || true

# --- U1: adapter artifacts ---
if [[ -f "$CE_ADAPTER" && -f "$CAPS" ]]; then
  echo "OK  code-review adapter + CAPABILITIES exist"
else
  echo "FAIL U1 adapter artifacts missing"
  FAIL=1
fi

if grep -q 'mode:agent' "$CE_ADAPTER" && grep -q 'code-review-normalize.sh' "$CE_ADAPTER" && \
   grep -qi 'run.dir scrub\|rm -rf' "$CE_ADAPTER"; then
  echo "OK  ce-code-review adapter documents invoke + scrub"
else
  echo "FAIL U1 adapter procedure"
  FAIL=1
fi

if grep -q 'fail-closed' "$CAPS" && grep -q 'ready-with-fixes' "$CAPS"; then
  echo "OK  CAPABILITIES contract enums documented"
else
  echo "FAIL U1 CAPABILITIES contract"
  FAIL=1
fi

# --- U1: normalize — complete + requirement filter ---
OUT=$(bash "$NORMALIZE" --input "$FIX/ce-complete.json" --repo-root "$ROOT")
if echo "$OUT" | jq -e '.status == "complete" and .verdict == "ready-with-fixes"' >/dev/null && \
   echo "$OUT" | jq -e '(.findings | length) == 1' >/dev/null && \
   echo "$OUT" | jq -e '.findings[0].title | test("null guard")' >/dev/null; then
  echo "OK  normalize: complete + requirement-stage filtered"
else
  echo "FAIL U1 normalize complete"
  echo "$OUT" | jq . 2>/dev/null || echo "$OUT"
  FAIL=1
fi

# Verdict mapping
for pair in "Ready to merge:ready" "Ready with fixes:ready-with-fixes" "Not ready:not-ready"; do
  src="${pair%%:*}"
  want="${pair##*:}"
  TMP=$(mktemp)
  jq --arg v "$src" '.verdict = $v | .findings = []' "$FIX/ce-complete.json" > "$TMP"
  got=$(bash "$NORMALIZE" --input "$TMP" --repo-root "$ROOT" | jq -r .verdict)
  if [[ "$got" == "$want" ]]; then
    echo "OK  verdict map: $src → $want"
  else
    echo "FAIL U1 verdict map $src (got $got)"
    FAIL=1
  fi
  rm -f "$TMP"
done

# Non-finding outcomes fail-closed
for f in ce-skipped ce-failed ce-degraded; do
  OUT=$(bash "$NORMALIZE" --input "$FIX/$f.json" --repo-root "$ROOT")
  st=$(echo "$OUT" | jq -r .status)
  fc=$(echo "$OUT" | jq -e '(.findings | length) == 0' >/dev/null && echo yes || echo no)
  if [[ "$fc" == "yes" && "$st" != "complete" ]]; then
    echo "OK  normalize fail-closed: $f"
  else
    echo "FAIL U1 fail-closed $f"
    FAIL=1
  fi
done

OUT=$(bash "$NORMALIZE" --input "$FIX/ce-malformed.json" --repo-root "$ROOT")
if echo "$OUT" | jq -e '.status == "failed"' >/dev/null; then
  echo "OK  normalize: malformed JSON → failed"
else
  echo "FAIL U1 malformed JSON"
  FAIL=1
fi

# --- U2: schema validation ---
EXAMPLE="$ROOT/.sw/workflow.config.example.json"
if jq -e '.review.local.enabled == true and .review.local.provider == "ce-code-review"' "$EXAMPLE" >/dev/null && \
   grep -q '"local"' "$SCHEMA"; then
  echo "OK  review.local in schema + example"
else
  echo "FAIL U2 config schema/example"
  FAIL=1
fi

# Unknown review.local key rejected (additionalProperties:false)
TMP_CFG=$(mktemp)
jq '.review.local.unknownKey = true' "$EXAMPLE" > "$TMP_CFG"
if command -v ajv >/dev/null 2>&1; then
  if ajv validate -s "$SCHEMA" -d "$TMP_CFG" 2>/dev/null; then
    echo "FAIL U2 unknown key should reject"
    FAIL=1
  else
    echo "OK  schema rejects unknown review.local key"
  fi
else
  if grep -q 'additionalProperties": false' "$SCHEMA" && grep -q '"local"' "$SCHEMA"; then
    echo "OK  schema additionalProperties:false on review.local (ajv not installed)"
  else
    echo "FAIL U2 schema structure"
    FAIL=1
  fi
fi
rm -f "$TMP_CFG"

# Gate configs validate structurally
if jq -e '.review.local.gate.surface | length == 4' "$EXAMPLE" >/dev/null && \
   jq -e '(.review.local.gate.haltOn | length) == 0' "$EXAMPLE" >/dev/null; then
  echo "OK  surface-only default gate in example"
else
  echo "FAIL U2 gate default"
  FAIL=1
fi

# --- U3: two-phase sw-review procedure ---
if grep -qi 'phase 1' "$SW_REVIEW" && grep -qi 'phase 2' "$SW_REVIEW" && \
   grep -q 'review.local' "$SW_REVIEW" && grep -q 'ce-code-review' "$SW_REVIEW" && \
   grep -q 'sw-review.status.json' "$SW_REVIEW" && \
   grep -qi 'CI gate' "$SW_REVIEW" && \
   grep -q 'rm -rf' "$SW_REVIEW" && grep -q 'memory-redact.sh' "$SW_REVIEW"; then
  echo "OK  sw-review two-phase + persist edges"
else
  echo "FAIL U3 sw-review procedure"
  FAIL=1
fi

if grep -qi 'skill not available' "$SW_REVIEW" && grep -qi 'fail-closed' "$CAPS"; then
  echo "OK  soft-dependency skip documented"
else
  echo "FAIL U3 skip path"
  FAIL=1
fi

# --- U4: apply + gate ---
set +e
OUT=$(bash "$GATE" --input "$FIX/normalized-for-gate.json" --gate-config "$FIX/gate-surface-only.json")
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | jq -e '.verdict == "continue" and .halt == false' >/dev/null; then
  echo "OK  gate surface-only continues"
else
  echo "FAIL U4 surface-only gate (ec=$EC)"
  FAIL=1
fi

set +e
OUT=$(bash "$GATE" --input "$FIX/normalized-for-gate.json" --gate-config "$FIX/gate-halting.json")
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | jq -e '.verdict == "halt" and .halt == true' >/dev/null && \
   echo "$OUT" | jq -e '(.surfaced | length) == 2 and (.surfaced[0].severity == "P1")' >/dev/null && \
   echo "$OUT" | jq -e '(.halt_findings | length) == 1 and (.halt_findings[0].severity == "P1")' >/dev/null; then
  echo "OK  gate halting mode halts"
else
  echo "FAIL U4 halting gate (ec=$EC)"
  echo "$OUT" | jq . 2>/dev/null || echo "$OUT"
  FAIL=1
fi

# Untrusted apply checks
ELIG='{"severity":"P2","file":"src/foo.ts","suggested_fix":"x=1","requires_verification":false}'
set +e
bash "$APPLY_CHECK" --finding "$ELIG" --repo-root "$ROOT" >/dev/null
EC=$?
set -e
if [[ "$EC" -eq 0 ]]; then
  echo "OK  apply-check eligible P2"
else
  echo "FAIL U4 eligible apply"
  FAIL=1
fi

TRAV='{"severity":"P2","file":"../../etc/passwd","suggested_fix":"x","requires_verification":false}'
set +e
bash "$APPLY_CHECK" --finding "$TRAV" --repo-root "$ROOT" >/dev/null
EC=$?
set -e
if [[ "$EC" -eq 20 ]]; then
  echo "OK  apply-check rejects path traversal"
else
  echo "FAIL U4 path traversal (ec=$EC)"
  FAIL=1
fi

SEC='{"severity":"P3","file":"src/auth/login.ts","suggested_fix":"x","requires_verification":false}'
set +e
bash "$APPLY_CHECK" --finding "$SEC" --repo-root "$ROOT" >/dev/null
EC=$?
set -e
if [[ "$EC" -eq 20 ]]; then
  echo "OK  apply-check rejects security-sensitive target"
else
  echo "FAIL U4 security target (ec=$EC)"
  FAIL=1
fi

P1='{"severity":"P1","file":"src/foo.ts","suggested_fix":"x","requires_verification":false}'
set +e
bash "$APPLY_CHECK" --finding "$P1" --repo-root "$ROOT" >/dev/null
EC=$?
set -e
if [[ "$EC" -eq 20 ]]; then
  echo "OK  apply-check rejects P1"
else
  echo "FAIL U4 P1 reject (ec=$EC)"
  FAIL=1
fi

if grep -q 'sw-local-review-gate-result' "$SW_SHIP" && grep -qi 'halt' "$SW_SHIP"; then
  echo "OK  sw-ship local review halt stop condition"
else
  echo "FAIL U4 sw-ship halt"
  FAIL=1
fi

SUBAGENT_DISPATCH="$(content_path rules/sw-subagent-dispatch.mdc)"
if grep -q 'Local review apply loop' "$SUBAGENT_DISPATCH"; then
  echo "OK  subagent-dispatch bounded apply/re-verify"
else
  echo "FAIL U4 circuit breaker doc"
  FAIL=1
fi

# --- U5: golden-schema contract drift ---
GOLDEN="$FIX/golden-schema.json"
for key in $(jq -r '.required_top_level_keys[]' "$GOLDEN"); do
  if jq -e --arg k "$key" 'has($k)' "$FIX/ce-complete.json" >/dev/null; then
    :
  else
    echo "FAIL U5 golden schema drift: missing top-level key $key"
    FAIL=1
  fi
done
if [[ $FAIL -eq 0 ]]; then
  echo "OK  golden-schema top-level keys present in fixture"
fi

# Drift guard: tampered fixture missing key should fail check
TAMPERED=$(mktemp)
jq 'del(.run_id)' "$FIX/ce-complete.json" > "$TAMPERED"
DRIFT=0
for key in $(jq -r '.required_top_level_keys[]' "$GOLDEN"); do
  if ! jq -e --arg k "$key" 'has($k)' "$TAMPERED" >/dev/null; then
    DRIFT=1
    break
  fi
done
rm -f "$TAMPERED"
if [[ "$DRIFT" -eq 1 ]]; then
  echo "OK  contract-drift guard detects missing key"
else
  echo "FAIL U5 drift guard"
  FAIL=1
fi

# verify.test registration
WF="$ROOT/.cursor/workflow.config.json"
if grep -q 'run-code-review-fixtures.sh' "$WF" 2>/dev/null; then
  echo "OK  verify.test includes code-review fixtures"
else
  echo "FAIL U5 verify.test registration"
  FAIL=1
fi

# --- U6: docs/rules ---
if grep -qi 'two-phase' "$CODE_REVIEW_RULES" && grep -qi 'local' "$CODE_REVIEW_RULES" && \
   grep -qi 'local-then-provider' "$SEQUENCING"; then
  echo "OK  rules document local-first two-phase review"
else
  echo "FAIL U6 docs/rules"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL code-review fixtures passed"
else
  echo "SOME code-review fixtures FAILED"
  exit 1
fi
