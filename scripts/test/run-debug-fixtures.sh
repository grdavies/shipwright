#!/usr/bin/env bash
# Fixture tests for debugging workstream (plan 004).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REDACT="$ROOT/scripts/memory-redact.sh"
RCA="$ROOT/skills/rca-core/SKILL.md"
FAIL=0

# --- U1: debug entry implemented (not deferred stub) ---
if grep -q '## Debug entry procedure' "$RCA" && \
   ! grep -q 'Deferred to debugging-workstream' "$RCA" && \
   grep -q 'Causal-chain gate' "$RCA" && \
   grep -q '## Stabilize entry procedure' "$RCA"; then
  echo "OK  rca-core debug entry + stabilize preserved"
else
  echo "FAIL rca-core missing debug entry or still stubbed"
  FAIL=1
fi

if [[ -f "$ROOT/skills/rca-core/references/debug-inputs.md" ]] && \
   grep -q 'sentry' "$ROOT/skills/rca-core/references/debug-inputs.md"; then
  echo "OK  debug-inputs reference"
else
  echo "FAIL debug-inputs.md"
  FAIL=1
fi

# --- U1: hard stops documented ---
if grep -q 'maxIterations' "$RCA" && grep -q 'No progress' "$RCA"; then
  echo "OK  rca-core hard stops"
else
  echo "FAIL rca-core hard stops"
  FAIL=1
fi

# --- U2: sentry recipe exists ---
if [[ -f "$ROOT/skills/debug/references/sentry.md" ]] && \
   grep -q 'memory-redact' "$ROOT/skills/debug/references/sentry.md" && \
   grep -qi 'degrad' "$ROOT/skills/debug/references/sentry.md"; then
  echo "OK  sentry MCP recipe + degradation"
else
  echo "FAIL sentry.md"
  FAIL=1
fi

# --- U2: Sentry-like payload redaction (ghp token in breadcrumb) ---
SENTRY_LIKE=$'breadcrumb: user clicked\nghp_abcdefghijklmnopqrstuvwxyz1234567890ABCD\nemail: leak@corp.example.com'
SCRUBBED=$(echo "$SENTRY_LIKE" | bash "$REDACT")
if [[ "$SCRUBBED" == *'[REDACTED:'* ]] && [[ "$SCRUBBED" != *'ghp_abc'* ]] && [[ "$SCRUBBED" != *'leak@corp'* ]]; then
  echo "OK  sentry payload redaction"
else
  echo "FAIL sentry payload redaction got: $SCRUBBED"
  FAIL=1
fi

# --- U3: sw-debug command + skill ---
if [[ -f "$ROOT/commands/sw-debug.md" ]] && \
   grep -qi 'not implement' "$ROOT/commands/sw-debug.md" && \
   grep -q 'memory-preflight' "$ROOT/commands/sw-debug.md"; then
  echo "OK  sw-debug command boundary"
else
  echo "FAIL sw-debug.md"
  FAIL=1
fi

if [[ -f "$ROOT/skills/debug/SKILL.md" ]] && \
   grep -q 'rca-core' "$ROOT/skills/debug/SKILL.md" && \
   grep -qi 'trivial fast-path' "$ROOT/skills/debug/SKILL.md"; then
  echo "OK  debug skill orchestrator"
else
  echo "FAIL skills/debug/SKILL.md"
  FAIL=1
fi

# --- U4: routing to 003/002 ---
if grep -q '/sw-worktree' "$ROOT/skills/debug/SKILL.md" && \
   grep -q '/sw-brainstorm' "$ROOT/skills/debug/SKILL.md" && \
   grep -q 'surface:debug-route' "$ROOT/skills/debug/SKILL.md"; then
  echo "OK  debug downstream routing"
else
  echo "FAIL debug routing sections"
  FAIL=1
fi

# --- sw-naming debug boundary ---
if grep -q '/sw-debug' "$ROOT/rules/sw-naming.mdc" && \
   grep -q 'Debug orchestrator boundary' "$ROOT/rules/sw-naming.mdc"; then
  echo "OK  sw-naming debug boundary"
else
  echo "FAIL sw-naming debug boundary"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL debug fixtures passed"
else
  echo "SOME debug fixtures FAILED"
  exit 1
fi
