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
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy()
    env["ROOT"] = str(root)
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts" / "test"), str(root / "scripts"), env.get("PYTHONPATH", "")) if p
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
# Tests for submit/session guardrail hooks (Cursor + Claude Code adapters).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="$ROOT/dist/cursor/hooks/before-submit-guardrails.py"
CLAUDE_SUBMIT="$ROOT/scripts/test/claude-submit-case.py"
CLAUDE_SESSION="$ROOT/scripts/test/claude-session-case.py"
FIX="$ROOT/scripts/test/fixtures"
TMP_WS="$(mktemp -d "${TMPDIR:-/tmp}/sw-hook-ws.XXXXXX")"
trap 'rm -rf "$TMP_WS"' EXIT

export PYTHONPATH="$ROOT/core/hooks:$ROOT/platforms/cursor:$ROOT/platforms/claude-code${PYTHONPATH:+:$PYTHONPATH}"

run_hook() {
  local rules_script="$1"
  local expect_continue="$2"
  local label="$3"
  local workspace="${4:-}"
  export SW_RULES_SCRIPT="$rules_script"
  unset SW_TEST_SUBMIT_RAISE
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

run_claude_submit() {
  local rules_script="$1"
  local expect_block="$2"
  local label="$3"
  local workspace="${4:-}"
  export SW_RULES_SCRIPT="$rules_script"
  set +e
  out=$(python3 "$CLAUDE_SUBMIT" "$workspace")
  ec=$?
  set -e
  decision=$(echo "$out" | jq -r '.decision // empty')
  if [ "$expect_block" = "true" ]; then
    if [ "$ec" -eq 2 ] && [ "$decision" = "block" ]; then
      echo "OK  $label claude-block ec=$ec"
    else
      echo "FAIL $label expected claude block ec=2 decision=block got ec=$ec decision=$decision"
      echo "$out" | jq . 2>/dev/null || echo "$out"
      return 1
    fi
  else
    if [ "$ec" -eq 0 ] && [ "$decision" != "block" ]; then
      echo "OK  $label claude-allow ec=$ec"
    else
      echo "FAIL $label expected claude allow ec=0 got ec=$ec decision=$decision"
      echo "$out" | jq . 2>/dev/null || echo "$out"
      return 1
    fi
  fi
}

FAIL=0
chmod +x "$FIX"/rules-*.sh
chmod +x "$CLAUDE_SUBMIT" "$CLAUDE_SESSION"

mkdir -p "$TMP_WS/.cursor"
echo '{"memory":{"guardrails":{"enforceBeforeSubmit":true}}}' > "$TMP_WS/.cursor/workflow.config.json"

run_hook "$FIX/rules-fail.sh" false "provider-unreachable" "$TMP_WS" || FAIL=1
run_claude_submit "$FIX/rules-fail.sh" true "claude-provider-unreachable" "$TMP_WS" || FAIL=1

out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | SW_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  greenfield-empty-rules continue=true"
else
  echo "FAIL greenfield-empty-rules expected continue=true got=$cont"
  FAIL=1
fi
run_claude_submit "$FIX/rules-empty.sh" false "claude-greenfield-empty-rules" "$TMP_WS" || FAIL=1

echo '{"memory":{"guardrails":{"requireRuleClass":true,"enforceBeforeSubmit":true}}}' > "$TMP_WS/.cursor/workflow.config.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | SW_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "false" ]; then
  echo "OK  strict-require-rule-class continue=false"
else
  echo "FAIL strict-require-rule-class expected continue=false got=$cont"
  FAIL=1
fi

UNCONFIGURED_WS="$(mktemp -d "${TMPDIR:-/tmp}/sw-hook-unconf.XXXXXX")"
out=$(echo '{"workspace_roots":["'"$UNCONFIGURED_WS"'"]}' | SW_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  unconfigured-repo continue=true"
else
  echo "FAIL unconfigured-repo expected continue=true got=$cont"
  FAIL=1
fi
rm -rf "$UNCONFIGURED_WS"

echo '{"memory":{"guardrails":{"enforceBeforeSubmit":false}}}' > "$TMP_WS/.cursor/workflow.config.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | SW_RULES_SCRIPT="$FIX/rules-empty.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  enforce-disabled continue=true"
else
  echo "FAIL enforce-disabled expected continue=true got=$cont"
  FAIL=1
fi

echo '{"memory":{"guardrails":{"enforceBeforeSubmit":true}}}' > "$TMP_WS/.cursor/workflow.config.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | SW_RULES_SCRIPT="$FIX/rules-ok.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "true" ]; then
  echo "OK  rules-present continue=true"
else
  echo "FAIL rules-present expected continue=true got=$cont"
  FAIL=1
fi
run_claude_submit "$FIX/rules-ok.sh" false "claude-rules-present" "$TMP_WS" || FAIL=1

echo 'not-json' > "$TMP_WS/.cursor/sw-memory-rule-allowlist.json"
out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | SW_RULES_SCRIPT="$FIX/rules-ok.sh" python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "false" ]; then
  echo "OK  corrupt-allowlist continue=false"
else
  echo "FAIL corrupt-allowlist expected continue=false got=$cont"
  FAIL=1
fi

out=$(echo '{"workspace_roots":["'"$TMP_WS"'"]}' | SW_TEST_SUBMIT_RAISE=1 python3 "$HOOK")
cont=$(echo "$out" | jq -r '.continue')
if [ "$cont" = "false" ]; then
  echo "OK  catch-all-exception cursor continue=false"
else
  echo "FAIL catch-all-exception cursor expected continue=false got=$cont"
  FAIL=1
fi

export SW_TEST_SUBMIT_RAISE=1
run_claude_submit "$FIX/rules-ok.sh" true "claude-catch-all-exception" "$TMP_WS" || FAIL=1
unset SW_TEST_SUBMIT_RAISE

session_out=$(python3 "$CLAUDE_SESSION" "$TMP_WS")
if echo "$session_out" | jq -e '.hookSpecificOutput.additionalContext | length > 0' >/dev/null; then
  echo "OK  claude-session-start additionalContext"
else
  echo "FAIL claude-session-start missing additionalContext"
  echo "$session_out" | jq . 2>/dev/null || echo "$session_out"
  FAIL=1
fi

exit "$FAIL"

"""
