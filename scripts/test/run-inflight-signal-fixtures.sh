#!/usr/bin/env bash
# In-flight signal writer fixtures (PRD 032 phase 1).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/inflight_signal.py"
SH="$ROOT/scripts/inflight-signal.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "inflight_signal.py missing"; exit 1; }
[[ -x "$SH" ]] || chmod +x "$SH"

init_repo() {
  local tmp="$1"
  mkdir -p "$tmp/docs/planning"
  cat >"$tmp/docs/planning/INDEX.md" <<'IDX'
# Planning units INDEX

<!-- planning-index:schema v1 -->
<!-- planning-index:structural begin -->

| id | type | title | status | visibility | edges |
| --- | --- | --- | --- | --- | --- |

<!-- planning-index:structural end -->
<!-- planning-index:derived begin -->

<!-- planning-index:derived end -->
<!-- planning-index:inFlight begin -->

<!-- planning-index:inFlight end -->
IDX
  mkdir -p "$tmp/.cursor"
  cat >"$tmp/.cursor/workflow.config.json" <<'CFG'
{"planningDir":"docs/planning"}
CFG
}

# --- inflight-write-read-clear ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  init_repo "$TMP"
  mkdir -p .cursor/sw-deliver-runs
  cat >.cursor/sw-deliver-state.demo.json <<'ST'
{"verdict":"running","target":{"type":"feat","slug":"demo","branch":"feat/demo"},"runId":"run-a"}
ST
  python3 "$PY" "$TMP" write --target feat/demo >/dev/null
  OUT=$(python3 "$PY" "$TMP" read --unit demo)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['tuple']['runId']=='run-a'" || exit 1
  python3 "$PY" "$TMP" clear --unit demo >/dev/null
  OUT2=$(python3 "$PY" "$TMP" read --unit demo)
  echo "$OUT2" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['tuple'] is None" || exit 1
) && ok "inflight-write-read-clear" || bad "inflight-write-read-clear"

# --- cross-clone-cas-takeover-failclosed ---
TMP2=$(mktemp -d)
(
  cd "$TMP2"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  init_repo "$TMP2"
  mkdir -p .cursor/sw-deliver-runs
  cat >.cursor/sw-deliver-state.demo.json <<'ST'
{"verdict":"running","target":{"type":"feat","slug":"demo","branch":"feat/demo"},"runId":"run-live"}
ST
  python3 "$PY" "$TMP2" write --target feat/demo >/dev/null
  cat >.cursor/sw-deliver-state.demo.json <<'ST'
{"verdict":"running","target":{"type":"feat","slug":"demo","branch":"feat/demo"},"runId":"run-other"}
ST
  if python3 "$PY" "$TMP2" write --target feat/demo >/dev/null 2>&1; then
    exit 1
  fi
  python3 "$PY" "$TMP2" write --target feat/demo --takeover --takeover-reason fixture >/dev/null
) && ok "cross-clone-cas-takeover-failclosed" || bad "cross-clone-cas-takeover-failclosed"

# --- override-logged-who-when-why ---
TMP3=$(mktemp -d)
(
  cd "$TMP3"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  init_repo "$TMP3"
  mkdir -p .cursor
  cat >.cursor/sw-deliver-state.demo.json <<'ST'
{"verdict":"running","target":{"type":"feat","slug":"demo","branch":"feat/demo"}}
ST
  python3 "$PY" "$TMP3" override-audit --target feat/demo --kind handoff --reason fixture >/dev/null
  python3 -c "
import json
s=json.load(open('.cursor/sw-deliver-state.demo.json'))
assert s['overrideAudit'][0]['kind']=='handoff'
assert s['overrideAudit'][0]['reason']=='fixture'
"
) && ok "override-logged-who-when-why" || bad "override-logged-who-when-why"

# --- inflight-tuple-no-secret ---
TMP4=$(mktemp -d)
(
  cd "$TMP4"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  init_repo "$TMP4"
  mkdir -p .cursor
  cat >.cursor/sw-deliver-state.demo.json <<'ST'
{"verdict":"running","target":{"type":"feat","slug":"demo","branch":"feat/demo"},"runId":"api_key:supersecret"}
ST
  if python3 "$PY" "$TMP4" write --target feat/demo >/dev/null 2>&1; then
    exit 1
  fi
) && ok "inflight-tuple-no-secret" || bad "inflight-tuple-no-secret"

# --- inflight-opaque-token-slot-reserved ---
SCHEMA="$ROOT/core/sw-reference/inflight-signal.schema.json"
python3 -c "
import json, re
s=json.load(open('$SCHEMA'))
assert 'oneOf' in s
props_cleartext = s['oneOf'][0]['properties']
props_opaque = s['oneOf'][1]['properties']
assert 'branch' in props_cleartext and 'branchToken' in props_opaque
assert re.match(props_opaque['branchToken']['pattern'], 'sha256:abcd1234ef567890')
" && ok "inflight-opaque-token-slot-reserved" || bad "inflight-opaque-token-slot-reserved"

[[ $FAIL -eq 0 ]] || exit 1
echo "run-inflight-signal-fixtures: PASS"
