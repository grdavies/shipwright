#!/usr/bin/env bash
# Fixtures for PRD 018 Phase 4 — web neutrality, docs, dist consolidation, fixture closure.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

SCHEMA="$ROOT/.sw/config.schema.json"
EXAMPLE="$ROOT/core/sw-reference/workflow.config.example.json"
README="$ROOT/README.md"
GETTING="$ROOT/docs/guides/getting-started.md"
CONFIG="$ROOT/docs/guides/configuration.md"
NAMING="$ROOT/core/rules/sw-naming.mdc"
WF="$ROOT/.cursor/workflow.config.json"

# --- web-config-neutral-defaults (R15) ---
if python3 - "$SCHEMA" "$EXAMPLE" <<'PY'
import json, sys
from pathlib import Path
schema = json.loads(Path(sys.argv[1]).read_text())
example = json.loads(Path(sys.argv[2]).read_text())
props = schema["properties"]
verify_e2e = props["verifyE2e"]["properties"]
assert verify_e2e["enabled"].get("default") is False
assert verify_e2e["provider"].get("default") == "none"
enrich = props["review"]["properties"]["local"]["properties"]["ui"]["properties"]["enrich"]
assert enrich.get("default") == "off"
wt = example.get("worktree") or {}
assert "scaffold" not in wt, "example must omit worktree.scaffold"
assert example.get("verifyE2e", {}).get("enabled") is False
assert example["review"]["local"]["ui"]["enrich"] == "off"
print("neutral defaults ok")
PY
then
  ok "web-config-neutral-defaults"
else
  bad "web-config-neutral-defaults"
fi

# --- portability-emitter-freshness (R16) ---
if bash "$ROOT/scripts/test/run-emitter-fixtures.sh" >/dev/null 2>&1; then
  ok "portability-emitter-freshness"
else
  bad "portability-emitter-freshness"
fi

# --- portability-docs-presence (R18) ---
DOC_FAIL=0
check_doc() {
  local file="$1" label="$2"
  shift 2
  for needle in "$@"; do
    if ! grep -qi "$needle" "$file" 2>/dev/null; then
      bad "portability-docs-presence: $label missing $needle"
      DOC_FAIL=1
    fi
  done
}
check_doc "$README" "README" "/sw-init" "per project" "base"
check_doc "$GETTING" "getting-started" "/sw-init" "worktree"
check_doc "$CONFIG" "configuration" "/sw-init" "ci.prTestPlanManifest" "verifyE2e" "product boundary"
check_doc "$CONFIG" "configuration" "GitHub" "host.tokenEnv"
[[ "$DOC_FAIL" -eq 0 ]] && ok "portability-docs-presence"

# --- init-docs-and-naming (R30/R33) ---
if grep -q '/sw-init' "$README" "$GETTING" "$CONFIG" && \
   grep -q 'sw-setup' "$CONFIG" && \
   grep -q '/sw-setup' "$NAMING" && \
   grep -q '/sw-init' "$NAMING"; then
  ok "init-docs-and-naming"
else
  bad "init-docs-and-naming"
fi

# --- verify.test registration (R17) ---
for runner in \
  run-portability-setup-fixtures.sh \
  run-portability-boundary-fixtures.sh \
  run-base-resolution-fixtures.sh \
  run-portability-closure-fixtures.sh; do
  if grep -q "$runner" "$WF" 2>/dev/null; then
    ok "verify.test registers $runner"
  else
    bad "verify.test missing $runner"
  fi
done

if [[ "$FAIL" -ne 0 ]]; then
  echo "run-portability-closure-fixtures: FAIL"
  exit 1
fi
echo "run-portability-closure-fixtures: PASS"
