#!/usr/bin/env bash
# Tests for before-submit-guardrails.py fail-closed behavior.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="$ROOT/hooks/before-submit-guardrails.py"
FIX="$ROOT/scripts/test/fixtures"
TMP_WS="$(mktemp -d "${TMPDIR:-/tmp}/pf-hook-ws.XXXXXX")"
trap 'rm -rf "$TMP_WS"' EXIT

export PYTHONPATH="$ROOT/hooks${PYTHONPATH:+:$PYTHONPATH}"

run_hook() {
  local rules_script="$1"
  local expect_continue="$2"
  local label="$3"
  local workspace="${4:-}"
  export PF_RULES_SCRIPT="$rules_script"
  local stdin_payload='{}'
  if [ -n "$workspace" ]; then
    stdin_payload='{"workspace_roots":["'"$workspace"'"]}'
  fi
  local out
  out=$(echo "$stdin_payload" | python3 "$HOOK")
  local cont
  cont=$(echo "$out" | jq -r '.continue')
  if [ "$cont" = "$expect_continue" ]; then
    echo "OK  $label continue=$cont"
  else
    echo "FAIL $label expected continue=$expect_continue got=$cont"
    echo "$out" | jq . 2>/dev/null || echo "$out"
    return 1
  fi
  if [ "$cont" = "false" ]; then
    if echo "$out" | grep -qE 'ghp_|AKIA|Bearer sk-'; then
      echo "FAIL $label block message leaked secret pattern"
      return 1
    fi
  fi
}

FAIL=0
chmod +x "$FIX"/rules-*.sh

mkdir -p "$TMP_WS/.cursor"
echo '{"memory":{"guardrails":{"enforceBeforeSubmit":true}}}' > "$TMP_WS/.cursor/workflow.config.json"

run_hook "$FIX/rules-fail.sh" false "provider-unreachable" "$TMP_WS" || FAIL=1

out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | PF_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  greenfield-empty-rules continue=true"
else
  echo "FAIL greenfield-empty-rules expected continue=true got=$cont"
  FAIL=1
fi

echo '{"memory":{"guardrails":{"requireRuleClass":true,"enforceBeforeSubmit":true}}}' > "$TMP_WS/.cursor/workflow.config.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | PF_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "false" ]; then
  echo "OK  strict-require-rule-class continue=false"
else
  echo "FAIL strict-require-rule-class expected continue=false got=$cont"
  FAIL=1
fi

UNCONFIGURED_WS="$(mktemp -d "${TMPDIR:-/tmp}/pf-hook-unconf.XXXXXX")"
out=$(echo '{"workspace_roots":["'"$UNCONFIGURED_WS"'"]}' | PF_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  unconfigured-repo continue=true"
else
  echo "FAIL unconfigured-repo expected continue=true got=$cont"
  FAIL=1
fi
rm -rf "$UNCONFIGURED_WS"

echo '{"memory":{"guardrails":{"enforceBeforeSubmit":false}}}' > "$TMP_WS/.cursor/workflow.config.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | PF_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  enforce-disabled continue=true"
else
  echo "FAIL enforce-disabled expected continue=true got=$cont"
  FAIL=1
fi

echo '{"memory":{"guardrails":{"enforceBeforeSubmit":true}}}' > "$TMP_WS/.cursor/workflow.config.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | PF_RULES_SCRIPT="$FIX/rules-ok.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  rules-present continue=true"
else
  echo "FAIL rules-present expected continue=true got=$cont"
  FAIL=1
fi

echo 'not-json' > "$TMP_WS/.cursor/pf-memory-rule-allowlist.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | PF_RULES_SCRIPT="$FIX/rules-ok.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "false" ]; then
  echo "OK  corrupt-allowlist continue=false"
else
  echo "FAIL corrupt-allowlist expected continue=false got=$cont"
  FAIL=1
fi

exit "$FAIL"
