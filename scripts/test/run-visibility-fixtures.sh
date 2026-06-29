#!/usr/bin/env bash
# PRD 034 Phase 1 — visibility resolver fixtures.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
RESOLVE="$ROOT/scripts/visibility-resolve.sh"
PY="$ROOT/scripts/planning_visibility.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- visibility-field-default-profile ---
if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile specs-public \
  --unit-json '{"id":"a","type":"prd","status":"proposed","title":"t"}') && \
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['visibility']=='public' and d['source']=='profile-default'"; then
  ok "visibility-field-default-profile:specs-public-prd"
else
  bad "visibility-field-default-profile:specs-public-prd"
fi

if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile all-private \
  --unit-json '{"id":"b","type":"prd","status":"proposed","title":"t"}') && \
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['visibility']=='private'"; then
  ok "visibility-field-default-profile:all-private"
else
  bad "visibility-field-default-profile:all-private"
fi

if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile all-public \
  --unit-json '{"id":"c","type":"brainstorm","status":"proposed","title":"t","visibility":"private"}') && \
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['visibility']=='private' and d['source']=='unit-field'"; then
  ok "visibility-field-default-profile:unit-override"
else
  bad "visibility-field-default-profile:unit-override"
fi

# --- content-class-default-visibility ---
if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile specs-public \
  --unit-json '{"id":"d","type":"brainstorm","status":"proposed","title":"t"}') && \
  echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['visibility']=='private'"; then
  ok "content-class-default-visibility:brainstorm-private"
else
  bad "content-class-default-visibility:brainstorm-private"
fi

if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile specs-public \
  --unit-json '{"id":"e","type":"gap","status":"open","title":"t"}') && \
  echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['visibility']=='private'"; then
  ok "content-class-default-visibility:gap-private"
else
  bad "content-class-default-visibility:gap-private"
fi

if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile specs-public \
  --unit-json '{"id":"f","type":"prd","status":"proposed","title":"t","contentClass":"tasks"}') && \
  echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['visibility']=='public'"; then
  ok "content-class-default-visibility:tasks-public"
else
  bad "content-class-default-visibility:tasks-public"
fi

# --- public-remote-default-resolution ---
(
  export SW_VISIBILITY_REMOTE_PROBE=public
  if OUT=$(python3 "$PY" --root "$ROOT" resolve-default-profile) && \
    echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['visibilityProfile']=='all-private'
assert d['privacyAck']['required'] is True
"; then
    ok "public-remote-default-resolution:public-remote"
  else
    bad "public-remote-default-resolution:public-remote"
  fi
)
(
  export SW_VISIBILITY_REMOTE_PROBE=private
  if OUT=$(python3 "$PY" --root "$ROOT" resolve-default-profile) && \
    echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['visibilityProfile']=='specs-public'
assert d['privacyAck']['required'] is False
"; then
    ok "public-remote-default-resolution:private-remote"
  else
    bad "public-remote-default-resolution:private-remote"
  fi
)

# --- resolver-single-authority ---
if OUT=$(python3 "$PY" --root "$ROOT" redact-body --visibility private --body "secret") && \
  [[ "$OUT" == *"redacted"* ]]; then
  ok "resolver-single-authority:redact-body"
else
  bad "resolver-single-authority:redact-body"
fi

if OUT=$(python3 "$PY" --root "$ROOT" emit-point --point index-active \
  --payload-json '{"visibility":"memory","body":"x","row":{"id":"u","title":"codename","body":"leak","status":"planned","type":"prd"}}') && \
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d['body'] != 'x'
assert 'body' not in d['row']
"; then
  ok "resolver-single-authority:emit-point"
else
  bad "resolver-single-authority:emit-point"
fi

if OUT=$(python3 "$PY" --root "$ROOT" emit-point --point inflight-tuple \
  --payload-json '{"visibility":"private","tuple":{"runId":"run-1","branch":"feat/secret","epoch":1}}') && \
  echo "$OUT" | python3 -c "
import json,sys
t=json.load(sys.stdin)['tuple']
assert 'branch' not in t and 'branchToken' in t
"; then
  ok "resolver-single-authority:inflight-tuple"
else
  bad "resolver-single-authority:inflight-tuple"
fi

if [[ -x "$RESOLVE" ]] && OUT=$("$RESOLVE" list-emission-points) && \
  echo "$OUT" | python3 -c "import json,sys; assert 'index-active' in json.load(sys.stdin)['points']"; then
  ok "resolver-single-authority:wrapper"
else
  bad "resolver-single-authority:wrapper"
fi

# --- failclosed-unknown-visibility ---
if OUT=$(python3 "$PY" --root "$ROOT" resolve-unit \
  --profile specs-public \
  --unit-json '{"id":"g","type":"prd","status":"proposed","title":"t","visibility":"bogus"}') && \
  echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin)['visibility']=='private'"; then
  ok "failclosed-unknown-visibility"
else
  bad "failclosed-unknown-visibility"
fi

if [[ "$FAIL" -ne 0 ]]; then
  echo "visibility fixtures: FAIL"
  exit 1
fi
echo "visibility fixtures: PASS"
exit 0
