#!/usr/bin/env bash
# PRD 016 PR test-plan CI enforcement fixture suite (R7).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

MANIFEST="$ROOT/core/sw-reference/pr-test-plan.manifest.json"
WORKFLOW="$ROOT/.github/workflows/pr-test-plan-ci.yml"
PR_TEMPLATE="$ROOT/.github/pull_request_template.md"
WF_CONFIG="$ROOT/.cursor/workflow.config.json"
GATE="$ROOT/scripts/check-gate.sh"
GATE_SKILL="$ROOT/core/skills/checks-gate/SKILL.md"
GATE_RULE="$ROOT/core/rules/checks-gate.mdc"
STABILIZE_SKILL="$ROOT/core/skills/stabilize-loop/SKILL.md"
CONFIG_GUIDE="$ROOT/docs/guides/configuration.md"
GENERATOR="$ROOT/scripts/generate-pr-test-plan-ci-workflow.sh"

# --- pr-test-plan-set-single-source (R1, R3) ---
if [[ -f "$MANIFEST" ]] && [[ -f "$WF_CONFIG" ]] && \
   grep -q 'run-pr-test-plan-manifest.sh' "$WF_CONFIG" && \
   grep -q 'pr-test-plan.manifest.json' "$WF_CONFIG"; then
  ok "pr-test-plan-set-single-source: verify.test consumes manifest"
else
  bad "pr-test-plan-set-single-source: manifest not wired in verify.test"
fi

TMP_WF="$(mktemp)"
trap 'rm -f "$TMP_WF"' EXIT
bash "$GENERATOR" "$TMP_WF" >/dev/null 2>&1
if cmp -s "$WORKFLOW" "$TMP_WF" 2>/dev/null; then
  ok "pr-test-plan-set-single-source: CI workflow matches manifest generator"
else
  bad "pr-test-plan-set-single-source: workflow drift — run bash scripts/generate-pr-test-plan-ci-workflow.sh"
fi

# --- pr-test-plan-jobs-on-pr (R1) ---
if grep -q 'pull_request:' "$WORKFLOW"; then
  ok "pr-test-plan-jobs-on-pr: workflow triggers on pull_request"
else
  bad "pr-test-plan-jobs-on-pr: missing pull_request trigger"
fi

while IFS= read -r job; do
  [[ -n "$job" ]] || continue
  if grep -q "^  ${job}:" "$WORKFLOW" && grep -q "name: ${job}" "$WORKFLOW"; then
    ok "pr-test-plan-jobs-on-pr: job ${job} present"
  else
    bad "pr-test-plan-jobs-on-pr: missing job ${job}"
  fi
done < <(
  python3 - "$MANIFEST" <<'PY'
import json, sys
for entry in json.load(open(sys.argv[1])).get("fixtures") or []:
    print(entry["ciJobName"])
PY
)

# --- pr-test-plan-blocking-classification (R2, R6) ---
python3 - "$MANIFEST" "$GATE" <<'PY' || { bad "pr-test-plan-blocking-classification: manifest/gate script"; }
import json, sys, pathlib
manifest = json.load(open(sys.argv[1]))
gate = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8")
classes = {e["classification"] for e in manifest.get("fixtures") or []}
assert "required" in classes and "advisory" in classes
assert "ADVISORY_JOBS" in gate and "REQUIRED_FAILING" in gate
assert "advisoryFailingChecks" in gate
print("OK  pr-test-plan-blocking-classification: manifest + gate split advisory/required")
PY

# --- pr-template-references-jobs (R4) ---
if [[ -f "$PR_TEMPLATE" ]] && \
   grep -q 'pr-test-plan-ci.yml' "$PR_TEMPLATE" && \
   grep -q 'feat-test-plan-doc-fixtures' "$PR_TEMPLATE" && \
   ! grep -q 'run-doc-fixtures.sh' "$PR_TEMPLATE"; then
  ok "pr-template-references-jobs: template cites CI job names not manual scripts"
else
  bad "pr-template-references-jobs: PR template must reference CI job names"
fi

# --- pr-test-plan-stabilize-consumes (R5) ---
if grep -q 'check-gate.sh' "$STABILIZE_SKILL" && \
   grep -q 'checks-gate' "$STABILIZE_SKILL" && \
   grep -q 'prTestPlan\|advisoryFailingChecks' "$STABILIZE_SKILL"; then
  ok "pr-test-plan-stabilize-consumes: stabilize-loop uses check-gate path"
else
  bad "pr-test-plan-stabilize-consumes: stabilize-loop missing gate integration"
fi

# --- pr-test-plan-checks-gate-verdict (R6) ---
if grep -q 'requiredFailingChecks\|advisoryFailingChecks' "$GATE_SKILL" && \
   grep -q 'prTestPlan' "$GATE_SKILL"; then
  ok "pr-test-plan-checks-gate-verdict: checks-gate skill documents advisory vs required"
else
  bad "pr-test-plan-checks-gate-verdict: checks-gate skill incomplete"
fi

# Advisory-only failure → green (reuse gate fixture harness)
export SW_GATE_FIXTURE=advisory-fail
export SW_GATE_NOW=1577838000
mkdir -p "$ROOT/scripts/test/bin"
cat > "$ROOT/scripts/test/bin/gh" <<'WRAP'
#!/usr/bin/env bash
exec "$(dirname "$0")/../gh-stub.sh" "$@"
WRAP
chmod +x "$ROOT/scripts/test/bin/gh"
set +e
OUT=$(PATH="$ROOT/scripts/test/bin:$PATH" bash "$GATE" 42 2>/dev/null)
EC=$?
set -e
VERDICT=$(echo "$OUT" | jq -r .verdict 2>/dev/null || echo "")
if [[ "$EC" -eq 0 && "$VERDICT" == "green" ]] && \
   echo "$OUT" | jq -e '.advisoryFailingChecks | length > 0' >/dev/null 2>&1; then
  ok "pr-test-plan-checks-gate-verdict: advisory failure non-blocking"
else
  bad "pr-test-plan-checks-gate-verdict: expected green with advisoryFailingChecks (ec=$EC verdict=$VERDICT)"
fi

# --- pr-test-plan-emitter-freshness (R7) ---
if bash "$ROOT/scripts/test/run-emitter-fixtures.sh" >/dev/null 2>&1; then
  ok "pr-test-plan-emitter-freshness"
else
  bad "pr-test-plan-emitter-freshness"
fi

# --- pr-test-plan-docs-presence (R7) ---
if grep -q 'pr-test-plan.manifest.json' "$GATE_RULE" && \
   grep -q 'pr-test-plan' "$CONFIG_GUIDE" && \
   grep -q 'pr-test-plan-ci.yml' "$CONFIG_GUIDE"; then
  ok "pr-test-plan-docs-presence: rule + guide describe enforcement"
else
  bad "pr-test-plan-docs-presence: missing docs in rule or configuration guide"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-pr-test-plan-fixtures: FAIL"
  exit 1
fi
echo "run-pr-test-plan-fixtures: PASS"
