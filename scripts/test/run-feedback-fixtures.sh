#!/usr/bin/env bash
# Fixture tests for feedback workstream (plan 005).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REDACT="$ROOT/scripts/memory-redact.sh"
FAIL=0

# --- U1: command + skill + schema ---
if [[ -f "$ROOT/commands/pf-feedback.md" ]] && \
   grep -qi 'does not' "$ROOT/commands/pf-feedback.md" && \
   grep -q 'untrusted_payload' "$ROOT/skills/feedback/references/signal-schema.md"; then
  echo "OK  pf-feedback intake + untrusted envelope"
else
  echo "FAIL pf-feedback intake files"
  FAIL=1
fi

if grep -q 'dedupKey' "$ROOT/skills/feedback/references/signal-schema.md" && \
   grep -q 'production' "$ROOT/skills/feedback/references/signal-schema.md" && \
   grep -q 'review' "$ROOT/skills/feedback/references/signal-schema.md" && \
   grep -q 'retro' "$ROOT/skills/feedback/references/signal-schema.md"; then
  echo "OK  signal schema three classes"
else
  echo "FAIL signal-schema.md classes"
  FAIL=1
fi

# --- U1: extended R41 redaction ---
DB_IN='postgres://user:secretpass@10.1.2.3:5432/app'
DB_OUT=$(echo "$DB_IN" | bash "$REDACT")
if [[ "$DB_OUT" == *'[REDACTED:DB_URL]'* ]] && [[ "$DB_OUT" != *'secretpass'* ]] && [[ "$DB_OUT" != *'10.1.2.3'* ]]; then
  echo "OK  redact DB connection string"
else
  echo "FAIL redact DB URL got: $DB_OUT"
  FAIL=1
fi

WEBHOOK_IN='whsec_abcdefghijklmnopqrstuvwxyz123456'
WEB_OUT=$(echo "$WEBHOOK_IN" | bash "$REDACT")
if [[ "$WEB_OUT" == *'[REDACTED:WEBHOOK_SECRET]'* ]] && [[ "$WEB_OUT" != *'whsec_'* ]]; then
  echo "OK  redact webhook secret"
else
  echo "FAIL redact webhook got: $WEB_OUT"
  FAIL=1
fi

HOST_IN='connecting to api.staging.internal retry'
HOST_OUT=$(echo "$HOST_IN" | bash "$REDACT")
if [[ "$HOST_OUT" == *'[REDACTED:INTERNAL_HOST]'* ]] && [[ "$HOST_OUT" != *'staging.internal'* ]]; then
  echo "OK  redact internal hostname"
else
  echo "FAIL redact internal host got: $HOST_OUT"
  FAIL=1
fi

IP_IN='retry from 10.1.2.3 after timeout'
IP_OUT=$(echo "$IP_IN" | bash "$REDACT")
if [[ "$IP_OUT" == *'[REDACTED:INTERNAL_IP]'* ]] && [[ "$IP_OUT" != *'10.1.2.3'* ]]; then
  echo "OK  redact internal IPv4"
else
  echo "FAIL redact internal IP got: $IP_OUT"
  FAIL=1
fi

SENTRY_IN='{"ip_address": "203.0.113.42", "username": "alice"}'
SENTRY_OUT=$(echo "$SENTRY_IN" | bash "$REDACT")
if [[ "$SENTRY_OUT" == *'[REDACTED:SENTRY_PII]'* ]] && [[ "$SENTRY_OUT" != *'203.0.113.42'* ]] && [[ "$SENTRY_OUT" != *'"alice"'* ]]; then
  echo "OK  redact Sentry JSON PII"
else
  echo "FAIL redact Sentry PII got: $SENTRY_OUT"
  FAIL=1
fi

ENTROPY_IN='password=P@ssw0rd1234567890abcdefghij'
ENTROPY_OUT=$(echo "$ENTROPY_IN" | bash "$REDACT")
if [[ "$ENTROPY_OUT" == *'[REDACTED:HIGH_ENTROPY_SECRET]'* ]] && [[ "$ENTROPY_OUT" != *'P@ssw0rd'* ]]; then
  echo "OK  redact high-entropy secret"
else
  echo "FAIL redact high-entropy got: $ENTROPY_OUT"
  FAIL=1
fi

# --- U1: untrusted_payload envelope ---
if grep -q 'UNTRUSTED_PAYLOAD_START' "$ROOT/skills/feedback/references/signal-schema.md" && \
   grep -q 'does not' "$ROOT/commands/pf-feedback.md"; then
  echo "OK  untrusted_payload envelope + no RCA in command"
else
  echo "FAIL untrusted_payload / command boundary"
  FAIL=1
fi

# --- U2: routing rubric ---
if grep -q '/pf-debug' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q '/pf-brainstorm' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q 'gap-capture' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q 'surface:feedback-route' "$ROOT/skills/feedback/references/route-record.md"; then
  echo "OK  feedback routing + route record"
else
  echo "FAIL feedback routing sections"
  FAIL=1
fi

if grep -q 'Conservative defaults' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q 'review' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q 'not.*debug' "$ROOT/skills/feedback/SKILL.md"; then
  echo "OK  review/retro not default to debug"
else
  echo "FAIL review-class routing default"
  FAIL=1
fi

# --- U3: gap-capture split ---
if grep -q '/pf-amend' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q 'GAP-BACKLOG' "$ROOT/skills/feedback/SKILL.md" && \
   grep -q 'source:feedback' "$ROOT/skills/feedback/SKILL.md"; then
  echo "OK  gap-capture amend vs backlog"
else
  echo "FAIL gap-capture split"
  FAIL=1
fi

# --- retro output contract pinned ---
if [[ -f "$ROOT/skills/retro/references/output-contract.md" ]] && \
   grep -q 'runId' "$ROOT/skills/retro/references/output-contract.md"; then
  echo "OK  retro output contract"
else
  echo "FAIL retro output-contract.md"
  FAIL=1
fi

# --- pf-naming feedback boundary ---
if grep -q 'Feedback orchestrator boundary' "$ROOT/rules/pf-naming.mdc"; then
  echo "OK  pf-naming feedback boundary"
else
  echo "FAIL pf-naming feedback boundary"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL feedback fixtures passed"
else
  echo "SOME feedback fixtures FAILED"
  exit 1
fi
