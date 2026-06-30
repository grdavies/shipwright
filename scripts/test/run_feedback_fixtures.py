#!/usr/bin/env python3
"""Ported fixture suite (R27) — embedded harness executed without on-disk shell files."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

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
# Fixture tests for feedback workstream (plan 005).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/test/fixture-lib.sh
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
REDACT="$ROOT/scripts/memory-redact.sh"
FAIL=0

# --- U1: command + skill + schema ---
if [[ -f "$(content_path commands/sw-feedback.md)" ]] && \
   grep -qi 'does not' "$(content_path commands/sw-feedback.md)" && \
   grep -q 'untrusted_payload' "$(content_path skills/feedback/references/signal-schema.md)"; then
  echo "OK  sw-feedback intake + untrusted envelope"
else
  echo "FAIL sw-feedback intake files"
  FAIL=1
fi

if grep -q 'dedupKey' "$(content_path skills/feedback/references/signal-schema.md)" && \
   grep -q 'production' "$(content_path skills/feedback/references/signal-schema.md)" && \
   grep -q 'review' "$(content_path skills/feedback/references/signal-schema.md)" && \
   grep -q 'retro' "$(content_path skills/feedback/references/signal-schema.md)"; then
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
if grep -q 'UNTRUSTED_PAYLOAD_START' "$(content_path skills/feedback/references/signal-schema.md)" && \
   grep -q 'does not' "$(content_path commands/sw-feedback.md)"; then
  echo "OK  untrusted_payload envelope + no RCA in command"
else
  echo "FAIL untrusted_payload / command boundary"
  FAIL=1
fi

# --- U2: routing rubric ---
if grep -q '/sw-debug' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q '/sw-brainstorm' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q 'gap-capture' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q 'surface:feedback-route' "$(content_path skills/feedback/references/route-record.md)"; then
  echo "OK  feedback routing + route record"
else
  echo "FAIL feedback routing sections"
  FAIL=1
fi

if grep -q 'Conservative defaults' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q 'review' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q 'not.*debug' "$(content_path skills/feedback/SKILL.md)"; then
  echo "OK  review/retro not default to debug"
else
  echo "FAIL review-class routing default"
  FAIL=1
fi

# --- U3: gap-capture split ---
if grep -q '/sw-amend' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q 'GAP-BACKLOG' "$(content_path skills/feedback/SKILL.md)" && \
   grep -q 'source:feedback' "$(content_path skills/feedback/SKILL.md)"; then
  echo "OK  gap-capture amend vs backlog"
else
  echo "FAIL gap-capture split"
  FAIL=1
fi

# --- retro output contract pinned ---
if [[ -f "$(content_path skills/retro/references/output-contract.md)" ]] && \
   grep -q 'runId' "$(content_path skills/retro/references/output-contract.md)"; then
  echo "OK  retro output contract"
else
  echo "FAIL retro output-contract.md"
  FAIL=1
fi

# --- sw-naming feedback boundary ---
if grep -q 'Feedback orchestrator boundary' "$(content_path rules/sw-naming.mdc)"; then
  echo "OK  sw-naming feedback boundary"
else
  echo "FAIL sw-naming feedback boundary"
  FAIL=1
fi

if [[ $FAIL -eq 0 ]]; then
  echo "ALL feedback fixtures passed"
else
  echo "SOME feedback fixtures FAILED"
  exit 1
fi

"""

if __name__ == "__main__":
    raise SystemExit(main())
