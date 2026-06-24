#!/usr/bin/env bash
# Fixtures for PRD 002 first-run onboarding UX (phase 1: config + gate honesty).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="$ROOT/.sw/config.schema.json"
FAIL=0

# --- config schema: doc.afterTasks + review.provider default ---
python3 - "$SCHEMA" <<'PY' || FAIL=1
import json, sys
from pathlib import Path

schema = json.loads(Path(sys.argv[1]).read_text())
props = schema["properties"]

doc = props.get("doc", {}).get("properties", {}).get("afterTasks", {})
assert doc.get("enum") == ["stop", "confirm", "auto"], doc.get("enum")
assert doc.get("default") == "confirm", doc.get("default")

review = props["review"]["properties"]
assert review["provider"]["default"] == "none", review["provider"]["default"]
assert "deprecated" in review["enabled"]["description"].lower(), review["enabled"]["description"]

example = Path(sys.argv[1]).parent / "workflow.config.example.json"
ex = json.loads(example.read_text())
assert ex.get("doc", {}).get("afterTasks") == "confirm"
assert ex.get("review", {}).get("provider") == "none"
print("OK  config-schema: doc.afterTasks + review.provider default none")
PY

# --- no literal disabled in gate emitter (root script) ---
if rg -n 'CR_STATE="disabled"|state=disabled|case.*disabled\)' \
  "$ROOT/scripts/check-gate.sh" "$ROOT/scripts/test/run-gate-fixtures.sh" 2>/dev/null; then
  echo "FAIL gate files still contain disabled literal"
  FAIL=1
else
  echo "OK  no disabled literal in gate emitter/fixtures"
fi

# --- gate fixtures (delegates to run-gate-fixtures) ---
bash "$ROOT/scripts/test/run-gate-fixtures.sh" || FAIL=1

# --- worktree guard (phase 2) ---
if [[ -x "$ROOT/scripts/sw-assert-worktree.sh" ]]; then
  bash "$ROOT/scripts/test/fixtures/onboarding-ux/worktree-guard-negative.sh" || FAIL=1
  bash "$ROOT/scripts/test/fixtures/onboarding-ux/worktree-guard-positive-linked.sh" || FAIL=1
  bash "$ROOT/scripts/test/fixtures/onboarding-ux/worktree-guard-positive-hotfix.sh" || FAIL=1
  if bash "$ROOT/scripts/sw-assert-worktree.sh" >/dev/null 2>&1; then
    echo "OK  worktree-guard: active worktree checkout passes"
  else
    echo "FAIL worktree-guard active worktree should pass"
    FAIL=1
  fi
else
  echo "FAIL sw-assert-worktree.sh missing or not executable"
  FAIL=1
fi

# --- verify.test registration ---
WF="$ROOT/.cursor/workflow.config.json"
if grep -q 'run-onboarding-ux-fixtures.sh' "$WF" 2>/dev/null; then
  echo "OK  verify.test registers onboarding-ux runner"
else
  echo "FAIL verify.test missing onboarding-ux runner"
  FAIL=1
fi

exit "$FAIL"
