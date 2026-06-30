#!/usr/bin/env bash
# Authoring-guard fixtures (PRD 032 phase 3 — R5/R6/R14).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

AG="$ROOT/scripts/authoring-guard.sh"
PY="$ROOT/scripts/inflight_signal.py"
REC="$ROOT/scripts/inflight_reconcile.py"

seed_repo() {
  local repo="$1"
  mkdir -p "$repo/docs/planning" "$repo/docs/prds/099-fixture-prd"
  cat >"$repo/docs/planning/INDEX.md" <<'IDX'
# Planning INDEX

<!-- region:inFlight -->
<!-- endregion:inFlight -->

<!-- region:derived -->
<!-- endregion:derived -->
IDX
}

write_tuple() {
  python3 - "$1" "$2" "$3" "$4" "$5" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from inflight_signal import InflightTuple, write_tuples
root = Path(sys.argv[2])
write_tuples(root, {sys.argv[3]: InflightTuple(run_id=sys.argv[4], epoch=1, branch=sys.argv[5])}, dry_run=False)
PY
}

# --- authoring-guard-inline-reconcile-then-failclosed (R5) ---
TMP1=$(mktemp -d)
(
  cd "$TMP1"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_repo "$TMP1"
  git add . && git commit -q -m init
  UNIT=prd-099-fixture-prd
  write_tuple "$ROOT/scripts" "$TMP1" "$UNIT" deliver-dead feat/dead
  mkdir -p .cursor
  echo '{"verdict":"complete"}' > .cursor/sw-deliver-state.dead.json
  bash "$AG" preflight --unit "$UNIT" --no-commit >/dev/null
  OUT=$(bash "$AG" preflight --path docs/prds/099-fixture-prd/tasks.md --no-commit)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['outcome']=='proceed'"
) && ok "authoring-guard-inline-reconcile-then-failclosed: stale cleared" || bad "authoring-guard-inline-reconcile-then-failclosed: stale"

TMP2=$(mktemp -d)
(
  cd "$TMP2"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_repo "$TMP2"
  touch docs/prds/099-fixture-prd/tasks.md
  git add . && git commit -q -m init
  git branch -q feat/live
  UNIT=prd-099-fixture-prd
  write_tuple "$ROOT/scripts" "$TMP2" "$UNIT" deliver-live feat/live
  mkdir -p .cursor
  cat > .cursor/sw-deliver-state.live.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/live"},"inflightLease":{"runId":"deliver-live","epoch":1}}
JSON
  set +e
  OUT=$(bash "$AG" preflight --unit "$UNIT" --no-commit 2>&1)
  EC=$?
  set -e
  [[ "$EC" -eq 20 ]]
  echo "$OUT" | python3 -c "import json,sys,re; m=re.findall(r'\{[\s\S]*?\}', sys.stdin.read()); d=json.loads(m[-1]); assert d.get('runId')=='deliver-live' and d.get('branch')=='feat/live'"
) && ok "authoring-guard-inline-reconcile-then-failclosed: live blocks" || bad "authoring-guard-inline-reconcile-then-failclosed: live"

# --- authoring-guard-shared-across-commands (R14) ---
for cmd in sw-amend sw-tasks sw-prd; do
  f="$ROOT/core/commands/${cmd}.md"
  grep -q 'authoring-guard.sh preflight' "$f" && grep -q 'import planning_paths' "$ROOT/core/scripts/authoring_guard.py" || { bad "authoring-guard-shared-across-commands: $cmd"; continue; }
  ok "authoring-guard-shared-across-commands: $cmd"
done

# --- handoff-artifact-surfaced-in-status (R6) ---
TMP3=$(mktemp -d)
(
  cd "$TMP3"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_repo "$TMP3"
  touch docs/prds/099-fixture-prd/tasks.md
  git add . && git commit -q -m init
  git branch -q feat/h
  UNIT=prd-099-fixture-prd
  write_tuple "$ROOT/scripts" "$TMP3" "$UNIT" deliver-h feat/h
  mkdir -p .cursor
  echo '{"verdict":"running","inflightLease":{"runId":"deliver-h","epoch":1}}' > .cursor/sw-deliver-state.h.json
  bash "$AG" preflight --path docs/prds/099-fixture-prd/tasks.md --command sw-amend --handoff "defer" --no-commit >/dev/null
  bash "$AG" list-handoffs | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['handoffs']"
  python3 - "$TMP3" <<'INNER'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
handoffs = json.loads((root / ".cursor/authoring-handoffs.json").read_text())["handoffs"]
assert handoffs and handoffs[0].get("artifact")
INNER
  grep -q 'authoringHandoffs' "$ROOT/scripts/reconcile.py"
) && ok "handoff-artifact-surfaced-in-status" || bad "handoff-artifact-surfaced-in-status"

rm -rf "$TMP1" "$TMP2" "$TMP3"
exit "$FAIL"
