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
from _harness_patch import harness_subprocess_env as _harness_env
from _harness_patch import patch_source as _patch_source


def main() -> int:
    root = repo_root(__file__)
    env = _harness_env(root)
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


# --- R5: complete-unit route guard (PRD 048) ---
SKILL="$(content_path skills/feedback/SKILL.md)"
CMD="$(content_path commands/sw-feedback.md)"
if grep -q 'authoring-guard.py preflight' "$SKILL" && \
   grep -q 'authoring-guard.py preflight' "$CMD" && \
   grep -q -- '--command sw-amend --no-commit' "$SKILL" && \
   grep -q -- '--command sw-amend --no-commit' "$CMD" && \
   grep -q 'propose_complete_change_route' "$SKILL" && \
   grep -q 'gap-amend-blocked' "$SKILL"; then
  echo "OK  feedback complete-unit route guard docs"
else
  echo "FAIL feedback complete-unit route guard docs"
  FAIL=1
fi

AG="$ROOT/scripts/authoring-guard.py"
PIG="$ROOT/scripts/planning_index_gen.py"
INDEX_MARKERS_START='<!-- planning-index:derived begin -->'
INDEX_MARKERS_END='<!-- planning-index:derived end -->'

seed_index() {
  local repo="$1"
  mkdir -p "$repo/docs/planning"
  cat >"$repo/docs/planning/INDEX.md" <<'IDX'
# Planning units INDEX

<!-- planning-index:schema v1 -->
<!-- Status precedence: lifecycle units read derived.status when populated, else structural status; gap units use structural status only. -->

<!-- planning-index:structural begin -->
| id | type | title | status | visibility | edges |
| --- | --- | --- | --- | --- | --- |
<!-- planning-index:structural end -->
<!-- planning-index:derived begin -->

<!-- planning-index:derived end -->
<!-- planning-index:inFlight begin -->

<!-- planning-index:inFlight end -->
IDX
}

seed_unit() {
  local repo="$1" type="$2" id="$3" status="$4"
  mkdir -p "$repo/docs/planning/$type/$id/amendments"
  cat >"$repo/docs/planning/$type/$id/$id.md" <<EOF
---
id: $id
type: $type
status: $status
title: Fixture unit
visibility: public
---
# body
EOF
}

inject_derived() {
  local repo="$1" body="$2"
  python3 - "$repo/docs/planning/INDEX.md" "$body" <<'PYINJ'
import sys
from pathlib import Path
idx = Path(sys.argv[1])
body = sys.argv[2]
text = idx.read_text()
start = "<!-- planning-index:derived begin -->"
end = "<!-- planning-index:derived end -->"
text = text.split(start, 1)[0] + start + "\n" + body + end + text.split(end, 1)[1]
idx.write_text(text)
PYINJ
}

snapshot_inflight() {
  local repo="$1"
  python3 - "$repo/docs/planning/INDEX.md" <<'PYSNAP'
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text()
start = "<!-- planning-index:inFlight begin -->"
end = "<!-- planning-index:inFlight end -->"
print(text.split(start,1)[1].split(end,1)[0])
PYSNAP
}

# complete unit routes away from /sw-amend (exit 21 + route payload)
TMP_R5C=$(mktemp -d)
(
  cd "$TMP_R5C"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP_R5C"
  seed_unit "$TMP_R5C" prd prd-048-fixture complete
  inject_derived "$TMP_R5C" $'prd-048-fixture: complete\n'
  git add . && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  BEFORE=$(snapshot_inflight "$TMP_R5C")
  set +e
  OUT=$(python3 "$AG" preflight --path docs/planning/prd/prd-048-fixture/prd-048-fixture.md --command sw-amend --no-commit 2>&1)
  EC=$?
  set -e
  AFTER=$(snapshot_inflight "$TMP_R5C")
  [[ "$EC" -eq 21 ]]
  [[ "$BEFORE" == "$AFTER" ]]
  echo "$OUT" | python3 -c "
import json,sys,re
m=re.findall(r'\{[\s\S]*\}', sys.stdin.read())
d=json.loads(m[-1])
assert d['outcome']=='route'
assert 'route' in d
r=d['route']
assert r['kind']=='extending-unit'
assert 'extends' in r['edges']
assert '/sw-amend' not in json.dumps(d)
"
) && echo "OK  feedback-r5-complete-unit-routes-not-amend" || { echo "FAIL feedback-r5-complete-unit-routes-not-amend"; FAIL=1; }

# planned unit still proceeds to /sw-amend path
TMP_R5P=$(mktemp -d)
(
  cd "$TMP_R5P"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP_R5P"
  seed_unit "$TMP_R5P" prd prd-048-fixture planned
  inject_derived "$TMP_R5P" $'prd-048-fixture: planned\n'
  git add . && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  OUT=$(python3 "$AG" preflight --path docs/planning/prd/prd-048-fixture/prd-048-fixture.md --command sw-amend --no-commit)
  echo "$OUT" | python3 -c "import json,sys,re; m=re.findall(r'\{[\s\S]*\}', sys.stdin.read()); d=json.loads(m[-1]); assert d['outcome']=='proceed'"
) && echo "OK  feedback-r5-planned-unit-proceeds-amend" || { echo "FAIL feedback-r5-planned-unit-proceeds-amend"; FAIL=1; }

# in-progress unit still proceeds
TMP_R5I=$(mktemp -d)
(
  cd "$TMP_R5I"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP_R5I"
  seed_unit "$TMP_R5I" prd prd-048-fixture in-progress
  inject_derived "$TMP_R5I" $'prd-048-fixture: in-progress\n'
  git add . && git commit --trailer "Co-authored-by: Cursor <cursoragent@cursor.com>" -q -m init
  OUT=$(python3 "$AG" preflight --path docs/planning/prd/prd-048-fixture/prd-048-fixture.md --command sw-amend --no-commit)
  echo "$OUT" | python3 -c "import json,sys,re; m=re.findall(r'\{[\s\S]*\}', sys.stdin.read()); d=json.loads(m[-1]); assert d['outcome']=='proceed'"
) && echo "OK  feedback-r5-in-progress-unit-proceeds-amend" || { echo "FAIL feedback-r5-in-progress-unit-proceeds-amend"; FAIL=1; }

if [[ $FAIL -eq 0 ]]; then
  echo "ALL feedback fixtures passed"
else
  echo "SOME feedback fixtures FAILED"
  exit 1
fi

"""

if __name__ == "__main__":
    raise SystemExit(main())
