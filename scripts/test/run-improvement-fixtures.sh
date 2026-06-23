#!/usr/bin/env bash
# Fixture tests for loop-improvement program (plan 2026-06-23-001).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STABILIZE="$ROOT/commands/pf-stabilize.md"
RCA="$ROOT/skills/rca-core/SKILL.md"
LOOP="$ROOT/skills/stabilize-loop/SKILL.md"
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

if [[ $FAIL -eq 0 ]]; then
  echo "ALL improvement fixtures passed"
else
  echo "SOME improvement fixtures FAILED"
  exit 1
fi
