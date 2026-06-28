#!/usr/bin/env bash
# Completed-unit immutability fixtures (PRD 032 phase 4 — R7/R8/R9/R12).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$(dirname "${BASH_SOURCE[0]}")/fixture-lib.sh"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

AG="$ROOT/scripts/authoring-guard.sh"
PY="$ROOT/scripts/authoring_guard.py"
PIG="$ROOT/scripts/planning_index_gen.py"
HOOK="$ROOT/core/hooks/pre-commit-completed-unit.sh"
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
  python3 - "$repo/docs/planning/INDEX.md" "$body" <<'PY'
import sys
from pathlib import Path
idx = Path(sys.argv[1])
body = sys.argv[2]
text = idx.read_text()
start = "<!-- planning-index:derived begin -->"
end = "<!-- planning-index:derived end -->"
text = text.split(start, 1)[0] + start + "\n" + body + end + text.split(end, 1)[1]
idx.write_text(text)
PY
}

# --- amend-refuses-complete-allows-planned (R7) ---
TMP1=$(mktemp -d)
(
  cd "$TMP1"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP1"
  seed_unit "$TMP1" prd prd-099-fixture planned
  inject_derived "$TMP1" $'prd-099-fixture: planned\n'
  git add . && git commit -q -m init
  OUT=$(bash "$AG" preflight --path docs/planning/prd/prd-099-fixture/prd-099-fixture.md --command sw-amend --no-commit)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['outcome']=='proceed'"
) && ok "amend-refuses-complete-allows-planned: planned proceeds" || bad "amend-refuses-complete-allows-planned: planned"

TMP1B=$(mktemp -d)
(
  cd "$TMP1B"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP1B"
  seed_unit "$TMP1B" prd prd-099-fixture planned
  inject_derived "$TMP1B" $'prd-099-fixture: in-progress\n'
  git add . && git commit -q -m init
  OUT=$(bash "$AG" preflight --path docs/planning/prd/prd-099-fixture/prd-099-fixture.md --command sw-amend --no-commit)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['outcome']=='proceed'"
) && ok "amend-refuses-complete-allows-planned: in-progress proceeds" || bad "amend-refuses-complete-allows-planned: in-progress"

TMP1C=$(mktemp -d)
(
  cd "$TMP1C"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP1C"
  seed_unit "$TMP1C" prd prd-099-fixture proposed
  inject_derived "$TMP1C" $'prd-099-fixture: proposed\n'
  git add . && git commit -q -m init
  set +e
  bash "$AG" preflight --path docs/planning/prd/prd-099-fixture/prd-099-fixture.md --command sw-amend --no-commit >/dev/null 2>&1
  EC=$?
  set -e
  [[ "$EC" -eq 20 ]]
) && ok "amend-refuses-complete-allows-planned: proposed refused" || bad "amend-refuses-complete-allows-planned: proposed"

TMP1D=$(mktemp -d)
(
  cd "$TMP1D"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP1D"
  seed_unit "$TMP1D" prd prd-099-fixture complete
  inject_derived "$TMP1D" $'prd-099-fixture: complete\n'
  git add . && git commit -q -m init
  set +e
  OUT=$(bash "$AG" preflight --path docs/planning/prd/prd-099-fixture/prd-099-fixture.md --command sw-amend --no-commit 2>&1)
  EC=$?
  set -e
  [[ "$EC" -eq 21 ]]
  echo "$OUT" | python3 -c "import json,sys,re; m=re.findall(r'\{[\s\S]*\}', sys.stdin.read()); d=json.loads(m[-1]); assert d['outcome']=='route'"
) && ok "amend-refuses-complete-allows-planned: complete refused" || bad "amend-refuses-complete-allows-planned: complete"

# --- complete-change-routes-to-new-unit (R8) ---
TMP2=$(mktemp -d)
(
  cd "$TMP2"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP2"
  seed_unit "$TMP2" prd prd-099-fixture complete
  inject_derived "$TMP2" $'prd-099-fixture: complete\n'
  git add . && git commit -q -m init
  set +e
  OUT=$(bash "$AG" preflight --unit prd-099-fixture --command sw-amend --no-commit 2>&1)
  EC=$?
  set -e
  [[ "$EC" -eq 21 ]]
  echo "$OUT" | python3 -c "
import json,sys,re
m=re.findall(r'\{[\s\S]*\}', sys.stdin.read())
d=json.loads(m[-1])
r=d['route']
assert r['kind']=='extending-unit'
assert 'extends' in r['edges']
assert r['edges']['extends']==['prd-099-fixture']
assert 'followup' in r['suggestedUnitId']
"
) && ok "complete-change-routes-to-new-unit: prd extends route" || bad "complete-change-routes-to-new-unit: prd"

TMP2B=$(mktemp -d)
(
  cd "$TMP2B"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP2B"
  seed_unit "$TMP2B" gap gap-099-fixture complete
  inject_derived "$TMP2B" $'gap-099-fixture: complete\n'
  git add . && git commit -q -m init
  set +e
  OUT=$(bash "$AG" preflight --unit gap-099-fixture --command sw-amend --no-commit 2>&1)
  EC=$?
  set -e
  [[ "$EC" -eq 21 ]]
  echo "$OUT" | python3 -c "
import json,sys,re
m=re.findall(r'\{[\s\S]*\}', sys.stdin.read())
d=json.loads(m[-1])
r=d['route']
assert r['kind']=='gap'
assert 'depends' in r['edges']
"
) && ok "complete-change-routes-to-new-unit: gap route" || bad "complete-change-routes-to-new-unit: gap"

# --- complete-unit-folder-mutation-rejected (R9) ---
TMP3=$(mktemp -d)
(
  cd "$TMP3"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP3"
  seed_unit "$TMP3" prd prd-099-fixture complete
  inject_derived "$TMP3" $'prd-099-fixture: complete\n'
  git add . && git commit -q -m init
  echo "mutated" >> docs/planning/prd/prd-099-fixture/prd-099-fixture.md
  git add docs/planning/prd/prd-099-fixture/prd-099-fixture.md
  set +e
  python3 "$PY" "$TMP3" check-staged >/dev/null 2>&1
  EC=$?
  set -e
  [[ "$EC" -eq 20 ]]
) && ok "complete-unit-folder-mutation-rejected: body edit" || bad "complete-unit-folder-mutation-rejected: body"

TMP3B=$(mktemp -d)
(
  cd "$TMP3B"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP3B"
  seed_unit "$TMP3B" prd prd-099-fixture complete
  inject_derived "$TMP3B" $'prd-099-fixture: complete\n'
  git add . && git commit -q -m init
  echo "# new amendment" > docs/planning/prd/prd-099-fixture/amendments/A1-test.md
  git add docs/planning/prd/prd-099-fixture/amendments/A1-test.md
  set +e
  python3 "$PY" "$TMP3B" check-staged >/dev/null 2>&1
  EC=$?
  set -e
  [[ "$EC" -eq 20 ]]
) && ok "complete-unit-folder-mutation-rejected: amendments subtree" || bad "complete-unit-folder-mutation-rejected: amendments"

# --- complete-flip-toctou-caught (R9) ---
TMP4=$(mktemp -d)
(
  cd "$TMP4"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP4"
  seed_unit "$TMP4" prd prd-099-fixture planned
  inject_derived "$TMP4" $'prd-099-fixture: planned\n'
  git add . && git commit -q -m init
  TOKEN=$(python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
from pathlib import Path
from authoring_guard import reconcile_generation_token
print(reconcile_generation_token(Path('$TMP4'), 'prd-099-fixture')['token'])
")
  inject_derived "$TMP4" $'prd-099-fixture: complete\n'
  echo "x" >> docs/planning/prd/prd-099-fixture/prd-099-fixture.md
  git add .
  set +e
  python3 "$PY" "$TMP4" check-staged --expect-token "$TOKEN" >/dev/null 2>&1
  EC=$?
  set -e
  [[ "$EC" -eq 20 ]]
) && ok "complete-flip-toctou-caught" || bad "complete-flip-toctou-caught"

# --- completed-hook-graceful-degrade-warns (R12) ---
TMP5=$(mktemp -d)
(
  cd "$TMP5"
  git init -q && git config user.email t@t.com && git config user.name T
  seed_index "$TMP5"
  seed_unit "$TMP5" prd prd-099-fixture complete
  git add . && git commit -q -m init
  echo "mutated" >> docs/planning/prd/prd-099-fixture/prd-099-fixture.md
  git add docs/planning/prd/prd-099-fixture/prd-099-fixture.md
  set +e
  OUT=$(python3 "$PY" "$TMP5" check-staged 2>&1)
  EC=$?
  set -e
  [[ "$EC" -eq 0 ]]
  echo "$OUT" | grep -q 'structural-degraded'
  echo "$OUT" | python3 -c "import json,sys,re; m=re.findall(r'\{[\s\S]*\}', sys.stdin.read()); d=json.loads(m[-1]); assert d.get('warnings')"
) && ok "completed-hook-graceful-degrade-warns" || bad "completed-hook-graceful-degrade-warns"

# --- hook wired in pre-commit chain ---
grep -q 'pre-commit-completed-unit.sh' "$ROOT/core/hooks/pre-commit" && \
grep -q 'complete-unit' "$ROOT/core/commands/sw-freeze.md" && \
grep -q 'complete' "$ROOT/core/commands/sw-amend.md" && \
ok "completed-unit-hook-wired-docs" || bad "completed-unit-hook-wired-docs"

rm -rf "$TMP1" "$TMP1B" "$TMP1C" "$TMP1D" "$TMP2" "$TMP2B" "$TMP3" "$TMP3B" "$TMP4" "$TMP5"
exit "$FAIL"
