#!/usr/bin/env bash
# In-flight signal writer fixtures (PRD 032 phase 1 — R1/R2/R11/R13/R17/R18).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/inflight_signal.py"
INF="$ROOT/scripts/inflight-signal.sh"
PIG="$ROOT/scripts/planning_index_gen.py"
FIX_SRC="$ROOT/scripts/test/fixtures/planning-index"
SCHEMA="$ROOT/core/sw-reference/inflight-tuple.schema.json"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "inflight_signal.py missing"; exit 1; }
[[ -x "$INF" ]] || chmod +x "$INF"

region_bytes() {
  local repo="$1" file="$2" region="$3"
  python3 - "$ROOT/scripts" "$repo/$file" "$region" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import planning_index_gen as pig
text = Path(sys.argv[2]).read_text()
r = pig.parse_regions(text)
print(getattr(r, sys.argv[3]), end="")
PY
}

seed_repo() {
  local dest="$1"
  mkdir -p "$dest/docs/planning"
  cp -R "$FIX_SRC/units/"* "$dest/docs/planning/"
  python3 "$PIG" "$dest" generate --writer generator >/dev/null
}

# --- inflight-write-read-clear (R1/R11) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$TMP2" "$TMP3" "$TMP4" "$TMP5" "$TMP6"' EXIT
(
  cd "$TMP"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP"
  git add docs/planning
  git commit -q -m "seed"
  mkdir -p .cursor
  cat > .cursor/sw-deliver-state.sample.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/sample"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md","prd_number":"031"}
JSON
  OUT=$(python3 "$PY" "$TMP" run-start --target feat/sample --unit prd-031-planning-unit-model --run-id deliver-sample --branch feat/sample --commit)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"
  CLONE=$(mktemp -d)
  git clone -q "$TMP" "$CLONE"
  READ=$(python3 "$PY" "$CLONE" read --unit prd-031-planning-unit-model)
  echo "$READ" | python3 -c "
import json,sys
d=json.load(sys.stdin)
t=d['tuple']
assert t and t['runId']=='deliver-sample'
assert t['branch']=='feat/sample'
assert t['epoch']>=1
"
  python3 "$PY" "$TMP" run-complete --target feat/sample --unit prd-031-planning-unit-model --commit >/dev/null
  AFTER=$(python3 "$PY" "$TMP" read --unit prd-031-planning-unit-model)
  echo "$AFTER" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['tuple'] is None"
  rm -rf "$CLONE"
) && ok "inflight-write-read-clear" || bad "inflight-write-read-clear"

# --- cross-clone-cas-takeover-failclosed (R2) ---
TMP2=$(mktemp -d)
(
  cd "$TMP2"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP2"
  git add docs/planning && git commit -q -m "seed"
  mkdir -p .cursor
  cat > .cursor/sw-deliver-state.a.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/a"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md","inflightLease":{"runId":"deliver-a","epoch":1}}
JSON
  python3 "$PY" "$TMP2" write --target feat/a --unit prd-031-planning-unit-model --run-id deliver-a --branch feat/a --epoch 1 >/dev/null
  git add docs/planning && git commit -q -m "inflight a" || true
  cat > .cursor/sw-deliver-state.b.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/b"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md"}
JSON
  set +e
  OUT=$(python3 "$PY" "$TMP2" write --target feat/b --unit prd-031-planning-unit-model --run-id deliver-b --branch feat/b 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -qi 'fail'
  OUT2=$(python3 "$PY" "$TMP2" write --target feat/b --unit prd-031-planning-unit-model --run-id deliver-b --branch feat/b --takeover "stale clone recovery")
  echo "$OUT2" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass', d"
  python3 -c "import json; assert json.load(open('.cursor/sw-deliver-state.b.json'))['overrideAudit'][-1]['action']=='takeover'"
) && ok "cross-clone-cas-takeover-failclosed" || bad "cross-clone-cas-takeover-failclosed"

# --- runstart-writer-inflight-region-only (R11) ---
TMP3=$(mktemp -d)
(
  cd "$TMP3"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP3"
  INDEX=docs/planning/INDEX.md
  python3 - "$INDEX" <<'PY'
import sys
from pathlib import Path
idx = Path(sys.argv[1])
text = idx.read_text()
start = "<!-- planning-index:derived begin -->"
end = "<!-- planning-index:derived end -->"
body = "prd-031-planning-unit-model: in-progress\n"
idx.write_text(text.split(start,1)[0]+start+"\n"+body+end+text.split(end,1)[1])
PY
  BEFORE=$(region_bytes "$TMP3" "$INDEX" derived)
  mkdir -p .cursor
  echo '{"verdict":"running","target":{"branch":"feat/x"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md"}' \
    > .cursor/sw-deliver-state.x.json
  python3 "$PY" "$TMP3" run-start --target feat/x --unit prd-031-planning-unit-model --run-id deliver-x --branch feat/x >/dev/null
  AFTER=$(region_bytes "$TMP3" "$INDEX" derived)
  [[ "$BEFORE" == "$AFTER" ]]
) && ok "runstart-writer-inflight-region-only" || bad "runstart-writer-inflight-region-only"

# --- inflight-opaque-token-slot-reserved (R13) ---
TMP4=$(mktemp -d)
(
  cd "$TMP4"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP4"
  mkdir -p .cursor
  echo '{"verdict":"running","target":{"branch":"feat/c"}}' > .cursor/sw-deliver-state.c.json
  python3 "$PY" "$TMP4" write --target feat/c --unit prd-031-planning-unit-model --run-id deliver-t1 --branch feat/cleartext --epoch 1 >/dev/null
  echo '{"verdict":"running","target":{"branch":"feat/c"}}' > .cursor/sw-deliver-state.c.json
  python3 "$PY" "$TMP4" write --target feat/c --unit prd-031-planning-unit-model --run-id deliver-t2 --branch-token deadbeefcafebabe --epoch 2 >/dev/null
  python3 - "$SCHEMA" <<'PY'
import json, sys
from pathlib import Path
try:
    import jsonschema
except ImportError:
    sys.exit(0)
schema = json.loads(Path(sys.argv[1]).read_text())
jsonschema.validate({"runId":"r","branch":"feat/x","epoch":1}, schema, cls=jsonschema.Draft7Validator)
jsonschema.validate({"runId":"r","branchToken":"deadbeefcafebabe","epoch":1}, schema, cls=jsonschema.Draft7Validator)
PY
) && ok "inflight-opaque-token-slot-reserved" || bad "inflight-opaque-token-slot-reserved"

# --- override-logged-who-when-why (R17) ---
for action in takeover handoff override; do
  TMP5=$(mktemp -d)
  (
    cd "$TMP5"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    seed_repo "$TMP5"
    mkdir -p .cursor
    cat > .cursor/sw-deliver-state.a.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/a"},"inflightLease":{"runId":"deliver-a","epoch":1}}
JSON
    python3 "$PY" "$TMP5" write --target feat/a --unit prd-031-planning-unit-model --run-id deliver-a --branch feat/a --epoch 1 >/dev/null
    cat > .cursor/sw-deliver-state.b.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/b"},"source_task_list":"docs/prds/031-planning-unit-model/tasks-031-planning-unit-model.md"}
JSON
    python3 "$PY" "$TMP5" write --target feat/b --unit prd-031-planning-unit-model --run-id deliver-b --branch feat/b --"$action" "test $action" >/dev/null
    python3 -c "
import json
log=json.load(open('.cursor/sw-deliver-state.b.json'))['overrideAudit']
assert log[-1]['action']=='$action'
assert log[-1]['who'] and log[-1]['when'] and log[-1]['why']
"
  ) && ok "override-logged-who-when-why-$action" || bad "override-logged-who-when-why-$action"
  rm -rf "$TMP5"
done

# --- inflight-tuple-no-secret (R18) ---
TMP6=$(mktemp -d)
(
  cd "$TMP6"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  seed_repo "$TMP6"
  set +e
  OUT=$(python3 "$PY" "$TMP6" validate --body $'run-id: x\nbranch: feat/y\nepoch: 1\nstatus: in-progress\n' 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]]
  set +e
  OUT2=$(bash "$ROOT/scripts/secret-scan.sh" inflight-tuple --body $'run-id: x\nbranch: ghp_abcdefghijklmnopqrstuvwxyz1234567890AB\nepoch: 1\n' 2>&1)
  EC2=$?
  set -e
  [[ "$EC2" -ne 0 ]]
) && ok "inflight-tuple-no-secret" || bad "inflight-tuple-no-secret"

exit "$FAIL"
