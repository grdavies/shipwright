#!/usr/bin/env bash
# Fixture tests for loop-improvement program (plan 2026-06-23-001).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STABILIZE="$ROOT/commands/pf-stabilize.md"
RCA="$ROOT/skills/rca-core/SKILL.md"
LOOP="$ROOT/skills/stabilize-loop/SKILL.md"
COMPOUND_SHIP="$ROOT/commands/pf-compound-ship.md"
SEQUENCING="$ROOT/rules/pf-workflow-sequencing.mdc"
FAIL=0

# --- U3: pf-stabilize routes through rca-core stabilize entry ---
if grep -q 'skills/rca-core/SKILL.md' "$STABILIZE" && \
   grep -qi 'stabilize entry' "$STABILIZE" && \
   grep -q '/tmp/pf-stabilize-gate.json' "$STABILIZE"; then
  echo "OK  pf-stabilize references rca-core stabilize entry"
else
  echo "FAIL pf-stabilize missing rca-core stabilize wiring"
  FAIL=1
fi

# --- U3: reply-before-resolve + per-head recompute retained ---
if grep -q 'reply before resolve' "$STABILIZE" && \
   grep -q 'headRefOid' "$STABILIZE" && \
   grep -q 'HEAD_SHA' "$STABILIZE"; then
  echo "OK  pf-stabilize reply-before-resolve + per-head guardrails retained"
else
  echo "FAIL pf-stabilize guardrails regressed"
  FAIL=1
fi

# --- U3: non-fix buckets bypass causal-chain gate ---
if grep -q 'resolve-with-evidence' "$STABILIZE" && \
   grep -q 'already-fixed-with-evidence' "$STABILIZE" && \
   grep -qi 'bypass' "$STABILIZE" && \
   grep -q 'fix-now' "$RCA" && \
   grep -qi 'bypass' "$RCA"; then
  echo "OK  non-fix ledger buckets bypass causal-chain gate"
else
  echo "FAIL causal-chain bypass not documented"
  FAIL=1
fi

# --- U3: single R29 ceiling — no nested rca-core loop ---
if grep -qi 'single pass' "$RCA" && \
   grep -qi 'not iterate' "$RCA" && \
   grep -q 'stabilize-loop' "$RCA" && \
   grep -qi 'maxIterations' "$LOOP" && \
   grep -qi 'not nested' "$LOOP"; then
  echo "OK  one R29 iteration ceiling (no nested rca-core loop)"
else
  echo "FAIL nested-loop guard missing"
  FAIL=1
fi

# --- U3: rca-core consumes harvested artifacts (no re-collect) ---
if grep -q '/tmp/pf-stabilize-threads.json' "$RCA" && \
   grep -q '/tmp/pf-stabilize-noninline.md' "$RCA" && \
   grep -q '/tmp/pf-stabilize-gate.json' "$RCA" && \
   grep -qi 'do not re-fetch' "$RCA"; then
  echo "OK  rca-core stabilize entry consumes harvested artifacts"
else
  echo "FAIL rca-core artifact consumption"
  FAIL=1
fi

# --- U4: rca-core three entries + debug hardening gates ---
DEBUG_SKILL="$ROOT/skills/debug/SKILL.md"
PF_DEBUG="$ROOT/commands/pf-debug.md"

if grep -qi 'stabilize' "$RCA" && \
   grep -qi 'debug' "$RCA" && \
   grep -qi 'dev-time' "$RCA" && \
   grep -q '## Dev-time entry procedure' "$RCA" && \
   grep -q '## Debug entry procedure' "$RCA" && \
   grep -q '## Stabilize entry procedure' "$RCA"; then
  echo "OK  rca-core documents three entries (stabilize, debug, dev-time)"
else
  echo "FAIL rca-core three-entry documentation"
  FAIL=1
fi

if grep -qi 'reproduction-first' "$DEBUG_SKILL" && \
   grep -qi 'failing-regression-test' "$DEBUG_SKILL"; then
  echo "OK  debug skill states reproduction-first + failing-regression-test gates"
else
  echo "FAIL debug skill gate documentation"
  FAIL=1
fi

if grep -qi 'rule-of-three' "$RCA" && grep -q 'R29' "$RCA" && \
   grep -qi 'rule-of-three' "$DEBUG_SKILL" && grep -q 'R29' "$DEBUG_SKILL"; then
  echo "OK  rule-of-three escalation references R29 hard stops"
else
  echo "FAIL rule-of-three / R29 wiring"
  FAIL=1
fi

if grep -qi 'dev-time' "$PF_DEBUG" && \
   grep -qi 'dev-time entry' "$PF_DEBUG" && \
   grep -qi 'test failure\|build failure\|verify failure' "$PF_DEBUG"; then
  echo "OK  pf-debug surfaces dev-time entry route"
else
  echo "FAIL pf-debug dev-time route"
  FAIL=1
fi

# --- U5: pf-compound-ship orchestrator exists with correct chain order ---
if [[ -f "$COMPOUND_SHIP" ]]; then
  echo "OK  pf-compound-ship command exists"
else
  echo "FAIL pf-compound-ship.md missing"
  FAIL=1
fi

if CHAIN_LINE=$(grep 'pf-retro' "$COMPOUND_SHIP" | grep 'pf-compound' | grep 'pf-status' | head -1) && \
   [[ -n "$CHAIN_LINE" ]] && \
   echo "$CHAIN_LINE" | grep -qE 'pf-retro.*pf-compound.*pf-status'; then
  echo "OK  compound-ship chain order retro → compound → status"
else
  echo "FAIL compound-ship chain order"
  FAIL=1
fi

if grep -qi 'never merge' "$COMPOUND_SHIP" && \
   grep -qi 'delegat' "$COMPOUND_SHIP" && \
   grep -qi 'never auto-promote rule' "$COMPOUND_SHIP"; then
  echo "OK  compound-ship guardrails (delegate, never merge, never auto-promote rules)"
else
  echo "FAIL compound-ship guardrails"
  FAIL=1
fi

if grep -q 'pf-compound-ship' "$SEQUENCING"; then
  echo "OK  pf-workflow-sequencing references pf-compound-ship"
else
  echo "FAIL pf-workflow-sequencing missing pf-compound-ship"
  FAIL=1
fi

# --- U1: verification-gate skill + verify-evidence.sh ---
VERIFY_EVIDENCE="$ROOT/scripts/verify-evidence.sh"
VERIFY_GATE_SKILL="$ROOT/skills/verification-gate/SKILL.md"
PF_VERIFY="$ROOT/commands/pf-verify.md"
PF_COMMIT="$ROOT/commands/pf-commit.md"
PF_SHIP="$ROOT/commands/pf-ship.md"
PF_READY="$ROOT/commands/pf-ready.md"
PF_REVIEW="$ROOT/commands/pf-review.md"
FIXTURES="$ROOT/scripts/test/fixtures/verify-evidence"

if [[ -f "$VERIFY_GATE_SKILL" ]] && [[ -x "$VERIFY_EVIDENCE" ]] && \
   grep -q 'pf-verify.status.json' "$PF_VERIFY" && \
   grep -q 'verify-evidence.sh' "$VERIFY_GATE_SKILL"; then
  echo "OK  verification-gate skill + script + pf-verify status emission"
else
  echo "FAIL verification-gate artifacts missing"
  FAIL=1
fi

# All required evidence passing → verified
set +e
OUT=$(bash "$VERIFY_EVIDENCE" \
  --verify-status "$FIXTURES/verify-pass.json" \
  --gate-json "$FIXTURES/gate-green.json" \
  --require-gate 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | jq -e '.verdict == "verified"' >/dev/null; then
  echo "OK  verify-evidence: all passing → verified"
else
  echo "FAIL verify-evidence verified case (ec=$EC)"
  FAIL=1
fi

# Fresh failing verify vs passing baseline → not-verified
set +e
OUT=$(bash "$VERIFY_EVIDENCE" \
  --verify-status "$FIXTURES/verify-fail.json" \
  --baseline-verify "$FIXTURES/verify-pass.json" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 20 ]] && echo "$OUT" | jq -e '.verdict == "not-verified"' >/dev/null; then
  echo "OK  verify-evidence: fresh failure → not-verified"
else
  echo "FAIL verify-evidence fresh failure case (ec=$EC)"
  FAIL=1
fi

# Missing required verify status → inconclusive
set +e
OUT=$(bash "$VERIFY_EVIDENCE" \
  --verify-status "$FIXTURES/does-not-exist.json" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 10 ]] && echo "$OUT" | jq -e '.verdict == "inconclusive"' >/dev/null; then
  echo "OK  verify-evidence: missing evidence → inconclusive"
else
  echo "FAIL verify-evidence missing evidence case (ec=$EC)"
  FAIL=1
fi

# No baseline + failing head → inconclusive (never not-verified)
set +e
OUT=$(bash "$VERIFY_EVIDENCE" \
  --verify-status "$FIXTURES/verify-fail.json" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 10 ]] && echo "$OUT" | jq -e '.verdict == "inconclusive"' >/dev/null; then
  echo "OK  verify-evidence: no baseline + fail → inconclusive"
else
  echo "FAIL verify-evidence no-baseline case (ec=$EC)"
  FAIL=1
fi

# Pre-existing unchanged failure → inconclusive
set +e
OUT=$(bash "$VERIFY_EVIDENCE" \
  --verify-status "$FIXTURES/verify-fail.json" \
  --baseline-verify "$FIXTURES/verify-fail.json" 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 10 ]] && echo "$OUT" | jq -e '.verdict == "inconclusive"' >/dev/null; then
  echo "OK  verify-evidence: pre-existing failure → inconclusive"
else
  echo "FAIL verify-evidence pre-existing case (ec=$EC)"
  FAIL=1
fi

# Review absent + verify/gate pass → verified
set +e
OUT=$(bash "$VERIFY_EVIDENCE" \
  --verify-status "$FIXTURES/verify-pass.json" \
  --gate-json "$FIXTURES/gate-green.json" \
  --require-gate 2>/dev/null)
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | jq -e '.evidence.review.status == "absent"' >/dev/null; then
  echo "OK  verify-evidence: review-disabled path → verified"
else
  echo "FAIL verify-evidence review-disabled case (ec=$EC)"
  FAIL=1
fi

# Determinism
RUN1=$(bash "$VERIFY_EVIDENCE" --verify-status "$FIXTURES/verify-pass.json" 2>/dev/null | jq -c .)
RUN2=$(bash "$VERIFY_EVIDENCE" --verify-status "$FIXTURES/verify-pass.json" 2>/dev/null | jq -c .)
if [[ "$RUN1" == "$RUN2" ]]; then
  echo "OK  verify-evidence: deterministic output"
else
  echo "FAIL verify-evidence determinism"
  FAIL=1
fi

# --- U2: wire verification gate into commit / ship (not pf-ready) ---
if grep -q 'verification-gate' "$PF_COMMIT" && \
   grep -q 'verify-evidence.sh' "$PF_COMMIT" && \
   grep -qi 'auditable override' "$PF_COMMIT" && \
   grep -qi 'check-gate' "$PF_COMMIT"; then
  echo "OK  pf-commit verification-gate precondition + bounded override"
else
  echo "FAIL pf-commit verification-gate wiring"
  FAIL=1
fi

if CHAIN_LINE=$(grep 'pf-verify' "$PF_SHIP" | grep 'verification-gate' | grep 'pf-commit' | head -1) && \
   [[ -n "$CHAIN_LINE" ]] && \
   echo "$CHAIN_LINE" | grep -qE 'pf-verify.*verification-gate.*pf-commit'; then
  echo "OK  pf-ship chain lists verification-gate between verify and commit"
else
  echo "FAIL pf-ship chain missing verification-gate step"
  FAIL=1
fi

if grep -qi 'inconclusive' "$PF_SHIP" && grep -qi 'log and continue' "$PF_SHIP"; then
  echo "OK  pf-ship continues on inconclusive"
else
  echo "FAIL pf-ship inconclusive policy"
  FAIL=1
fi

if grep -qi 'not-verified' "$PF_SHIP" && grep -qi 'halt' "$PF_SHIP"; then
  echo "OK  pf-ship halts on not-verified"
else
  echo "FAIL pf-ship not-verified halt"
  FAIL=1
fi

if grep -q 'pf-review.status.json' "$PF_REVIEW"; then
  echo "OK  pf-review emits stable review status file"
else
  echo "FAIL pf-review status emission"
  FAIL=1
fi

if grep -qi 'does not run verification-gate' "$PF_READY" && \
   grep -q 'check-gate.sh' "$PF_READY"; then
  echo "OK  pf-ready uses check-gate only (no verification-gate)"
else
  echo "FAIL pf-ready gate authority"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL improvement fixtures passed"
else
  echo "SOME improvement fixtures FAILED"
  exit 1
fi
