#!/usr/bin/env bash
# PRD 013 Testing Strategy — aggregate fixture runner (R18).
# Verifies every named scenario is implemented and delegates to phase fixture scripts.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ALL_OUT=""
TRACE_FILE=$(mktemp)
trap 'rm -f "$TRACE_FILE"' EXIT

ok()   { echo "OK  $1"; ALL_OUT+="OK  $1"$'\n'; echo "OK  $1" >> "$TRACE_FILE"; }
bad()  { echo "FAIL $1"; ALL_OUT+="FAIL $1"$'\n'; FAIL=1; }

run_suite() {
  local script="$1"
  local out
  if out=$(bash "$ROOT/scripts/test/$script" 2>&1); then
    echo "SUITE PASS $script"
    echo "$out"
    ALL_OUT+="$out"$'\n'
  else
    echo "SUITE FAIL $script"
    echo "$out"
    ALL_OUT+="$out"$'\n'
    FAIL=1
  fi
}

for suite in \
  run-state-fixtures.sh \
  run-orchestrator-fixtures.sh \
  run-deliver-fixtures.sh \
  run-deliver-loop-fixtures.sh \
  run-cleanup-fixtures.sh \
  run-emitter-fixtures.sh
do
  run_suite "$suite"
done

STATE_PY="$ROOT/scripts/wave_state.py"
SEED_PY="$ROOT/scripts/wave_spec_seed.py"
LOOP_PY="$ROOT/scripts/wave_deliver_loop.py"
TERM_PY="$ROOT/scripts/wave_terminal.py"
COMPOUND_PY="$ROOT/scripts/wave_compound.py"

# --- freeze-commit-on-feature-branch (R1, R3) ---
FC_FIX=$(mktemp -d)
(
  cd "$FC_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p docs/prds/099-freeze-commit
  cat >docs/prds/099-freeze-commit/tasks-099-freeze-commit.md <<'EOF'
---
frozen: true
topic: freeze-commit-fixture
---
### 1. Demo phase
EOF
  git add docs/prds/099-freeze-commit/
  git commit -q -m 'add frozen tasks on main'
  if OUT=$(python3 "$SEED_PY" "$FC_FIX" spec-seed \
      --artifact docs/prds/099-freeze-commit/tasks-099-freeze-commit.md 2>&1) && \
     echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('branch')=='feat/freeze-commit-fixture'
assert d.get('commit') or d.get('skipped')
" && [[ "$(git -C "$FC_FIX" branch --show-current)" == "main" ]] && \
     git -C "$FC_FIX" rev-parse --verify refs/heads/feat/freeze-commit-fixture >/dev/null; then
    ok "freeze-commit-on-feature-branch"
  else
    bad "freeze-commit-on-feature-branch"
  fi
) || bad "freeze-commit-on-feature-branch"
rm -rf "$FC_FIX"

# --- freeze-commit-idempotent-docs-only (R2) ---
IDEM_FIX=$(mktemp -d)
(
  cd "$IDEM_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  mkdir -p docs/prds/099-idem docs/brainstorms scripts
  cat >docs/prds/099-idem/tasks-099-idem.md <<'EOF'
---
frozen: true
topic: idem-fixture
---
### 1. Demo
EOF
  echo 'leak' >scripts/should-not-commit.py
  echo 'brainstorm' >docs/brainstorms/099-idem.md
  git add docs/prds/099-idem/
  git commit -q -m 'tasks only'
  python3 "$SEED_PY" "$IDEM_FIX" spec-seed \
    --artifact docs/prds/099-idem/tasks-099-idem.md >/dev/null
  if python3 "$SEED_PY" "$IDEM_FIX" spec-seed \
      --artifact docs/prds/099-idem/tasks-099-idem.md 2>/dev/null | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('skipped') is True
" && ! git -C "$IDEM_FIX" ls-tree -r feat/idem-fixture --name-only | grep -q brainstorms && \
     ! git -C "$IDEM_FIX" ls-tree -r feat/idem-fixture --name-only | grep -q should-not-commit; then
    ok "freeze-commit-idempotent-docs-only"
  else
    bad "freeze-commit-idempotent-docs-only"
  fi
) || bad "freeze-commit-idempotent-docs-only"
rm -rf "$IDEM_FIX"

# --- freeze-commit-verdict-independent (R4) ---
set +e
OUT=$(bash "$ROOT/scripts/check-frozen.sh" freeze-commit \
  --artifact docs/prds/__fixture-missing__/tasks-missing.md 2>&1)
EC=$?
set -e
if [[ "$EC" -eq 0 ]] && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('verdict')=='warn'
assert d.get('action')=='freeze-commit'
"; then
  ok "freeze-commit-verdict-independent"
else
  bad "freeze-commit-verdict-independent ec=$EC"
fi

# --- freeze-seed-single-source (R5) ---
if grep -qE 'check-frozen\.sh freeze-commit' "$ROOT/core/commands/sw-freeze.md" && \
   grep -qE 'wave\.sh.*spec-seed' "$ROOT/scripts/check-frozen.sh" && \
   echo "$ALL_OUT" | grep -qE 'OK  spec-seed-single-owner-idempotent'; then
  ok "freeze-seed-single-source"
else
  bad "freeze-seed-single-source"
fi

# --- deliver-lock-no-cross-block (R7) ---
LOCK_FIX=$(mktemp -d)
(
  cd "$LOCK_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  mkdir -p .cursor
  python3 "$STATE_PY" "$LOCK_FIX" lock acquire --target feat/alpha --nonblock >/dev/null
  python3 "$STATE_PY" "$LOCK_FIX" lock acquire --target feat/beta --nonblock >/dev/null
  set +e
  python3 "$STATE_PY" "$LOCK_FIX" lock acquire --target feat/alpha --nonblock 2>/dev/null
  EC_SAME=$?
  set -e
  if [[ -f .cursor/sw-deliver-alpha.lock && -f .cursor/sw-deliver-beta.lock && "$EC_SAME" -eq 20 ]]; then
    ok "deliver-lock-no-cross-block"
  else
    bad "deliver-lock-no-cross-block ec=$EC_SAME"
  fi
  python3 "$STATE_PY" "$LOCK_FIX" lock release --target feat/alpha >/dev/null 2>&1 || true
  python3 "$STATE_PY" "$LOCK_FIX" lock release --target feat/beta >/dev/null 2>&1 || true
) || bad "deliver-lock-no-cross-block"
rm -rf "$LOCK_FIX"

# --- deliver-identity-scoped (R8) ---
if python3 - <<'PY' "$ROOT"
import sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts"))
from wave_deliver_loop import assert_run_identity

alpha = {
    "verdict": "running",
    "source_task_list": "docs/prds/alpha-test/tasks-alpha-test.md",
    "target": {"branch": "feat/alpha-test"},
    "phases": {"1": {"id": "1", "slug": "a", "status": "pending"}},
}
beta_list = "docs/prds/beta-test/tasks-beta-test.md"
try:
    assert_run_identity(root, alpha, "docs/prds/alpha-test/tasks-alpha-test.md", [])
except SystemExit:
    raise SystemExit(1)
# Same-scope mismatch must still refuse
beta = dict(alpha)
beta["source_task_list"] = beta_list
try:
    assert_run_identity(root, beta, "docs/prds/alpha-test/tasks-alpha-test.md", [])
    raise SystemExit(1)
except SystemExit as exc:
    if exc.code not in (20, 2):
        raise
PY
then
  ok "deliver-identity-scoped"
else
  bad "deliver-identity-scoped"
fi

# --- deliver-no-repo-wide-path (R9) ---
AUDITED=(
  scripts/wave_deliver.py
  scripts/wave_deliver_loop.py
  scripts/wave_merge.py
  scripts/wave_lifecycle.py
  scripts/wave_bookkeeping.py
  scripts/wave_memory.py
  scripts/wave_failure.py
  scripts/wave_compound.py
  scripts/wave_terminal.py
  scripts/wave_living_docs.py
  scripts/wave_state.py
  scripts/tasks-currency-gate.sh
  scripts/docs-currency-gate.sh
  scripts/ship-phase-status.sh
  scripts/cleanup_lib.py
  scripts/reconcile-status.sh
)
if python3 - <<'PY' "$ROOT" "${AUDITED[@]}"
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
files = [Path(p) for p in sys.argv[2:]]
bad_hits = []
legacy_ok = re.compile(
    r"LEGACY_|legacy_paths|migrate_legacy|legacy repo-wide|legacy state|"
    r"migration|breadcrumb|superseded|STATE_PATH_NAME",
    re.I,
)
for path in files:
    text = path.read_text(encoding="utf-8")
    for i, line in enumerate(text.splitlines(), 1):
        if ".cursor/sw-deliver-state.json" in line or ".cursor/sw-deliver.lock" in line:
            if legacy_ok.search(line):
                continue
            if path.name == "wave_state.py" and "LEGACY_" in line:
                continue
            bad_hits.append(f"{path}:{i}:{line.strip()}")
if bad_hits:
    print("\n".join(bad_hits))
    sys.exit(1)
sys.exit(0)
PY
then
  ok "deliver-no-repo-wide-path"
else
  bad "deliver-no-repo-wide-path"
fi

# --- deliver-canonical-state-write (R28) ---
CANON_FIX=$(mktemp -d)
(
  cd "$CANON_FIX"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -qb feat/canonical-test
  git commit --allow-empty -q -m feat
  mkdir -p .cursor
  cat >.cursor/sw-deliver-state.canonical-test.json <<'JSON'
{"verdict":"running","target":{"branch":"feat/canonical-test"},"phases":{"1":{"slug":"a","status":"green-merged"}}}
JSON
  mkdir -p .sw-worktrees/fake-orchestrator/.cursor
  echo '{"verdict":"running","stale":true}' >.sw-worktrees/fake-orchestrator/.cursor/sw-deliver-state.canonical-test.json
  BEFORE=$(cat .cursor/sw-deliver-state.canonical-test.json)
  python3 "$COMPOUND_PY" "$CANON_FIX/.sw-worktrees/fake-orchestrator" compound-ship record-premerge \
    --prd 013 --phase canonical --skip-append-log >/dev/null
  AFTER=$(cat .cursor/sw-deliver-state.canonical-test.json)
  STALE=$(cat .sw-worktrees/fake-orchestrator/.cursor/sw-deliver-state.canonical-test.json)
  if [[ "$BEFORE" != "$AFTER" ]] && echo "$AFTER" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('compoundShip',{}).get('premergeDone') is True
" && echo "$STALE" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert d.get('stale') is True
"; then
    ok "deliver-canonical-state-write"
  else
    exit 1
  fi
) || bad "deliver-canonical-state-write"
rm -rf "$CANON_FIX"

# --- deliver-terminal-autonomous-watch-stabilize (R22) ---
SHIP_FIX=$(mktemp -d)
(
  cd "$SHIP_FIX"
  git init -q
  git config user.email t@t.com
  git config user.name T
  git commit --allow-empty -q -m init
  git branch -M main
  git checkout -qb feat/terminal-ship
  mkdir -p .cursor
  echo '{"defaultBaseBranch":"main","deliver":{"terminal":{"autonomy":"auto"},"remediation":{"maxAttempts":2}}}' \
    >.cursor/workflow.config.json
  echo '{"verdict":"running","prd_number":"013","target":{"branch":"feat/terminal-ship"},"phases":{"1":{"status":"green-merged","slug":"a"}},"compoundShip":{"premergeDone":true}}' \
    >.cursor/sw-deliver-state.terminal-ship.json
  if OUT=$(python3 "$TERM_PY" "$SHIP_FIX" terminal ship run --dry-run 2>/dev/null) && \
     echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
steps=d.get('steps',[])
assert 'gate-watch' in steps
assert 'stabilize-within-budget' in steps
assert d.get('neverAutoMergesMain') is True
"; then
    ok "deliver-terminal-autonomous-watch-stabilize"
  else
    exit 1
  fi
) || bad "deliver-terminal-autonomous-watch-stabilize"
rm -rf "$SHIP_FIX"

# --- deliver-concurrency-emitter-freshness (R17) ---
if echo "$ALL_OUT" | grep -qE 'OK  freshness dist matches generate'; then
  ok "deliver-concurrency-emitter-freshness"
else
  bad "deliver-concurrency-emitter-freshness"
fi

# --- deliver-concurrency-docs-presence (R19) ---
if grep -qiE 'sw-deliver-state\.<slug>' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qiE 'freeze-time commit|Freeze-time commit' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qiE 'concurrent-run index|runs index' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qiE 'v1 deferrals|cross-feature waves' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qiE 'canonical.*repo root|single canonical' "$ROOT/.sw/layout.md" && \
   grep -qiE 'scoped deliver state|per-branch scoped' "$ROOT/core/skills/conductor/SKILL.md" && \
   grep -qiE 'freeze-time commit|scoped deliver' "$ROOT/core/rules/sw-workflow-sequencing.mdc" && \
   grep -qiE 'scoped deliver state|sw-deliver-state\.' "$ROOT/docs/guides/workflows.md"; then
  ok "deliver-concurrency-docs-presence"
else
  bad "deliver-concurrency-docs-presence"
fi

# --- terminal-autonomy-docs-presence (R27) ---
if grep -qE 'deliver\.terminal\.autonomy' "$ROOT/core/skills/deliver/SKILL.md" && \
   grep -qE 'terminal-ship|terminal ship' "$ROOT/core/skills/conductor/SKILL.md" && \
   grep -qE 'cleanup\.autonomy' "$ROOT/core/commands/sw-cleanup.md" && \
   grep -qE 'terminal\.autonomy|cleanup\.autonomy' "$ROOT/core/rules/sw-workflow-sequencing.mdc"; then
  ok "terminal-autonomy-docs-presence"
else
  bad "terminal-autonomy-docs-presence"
fi

# PRD 013 traceability registry — every fixture name must appear in suite output
FIXTURES=(
  freeze-commit-on-feature-branch
  freeze-commit-idempotent-docs-only
  freeze-commit-verdict-independent
  freeze-seed-single-source
  deliver-state-scoped-per-branch
  deliver-lock-no-cross-block
  deliver-identity-scoped
  deliver-no-repo-wide-path
  deliver-run-index-enumerates
  deliver-legacy-state-migration
  deliver-living-doc-serialized
  deliver-cross-feature-wave-plan
  deliver-file-set-edge-inference
  deliver-live-phase-status
  deliver-contention-durable-feedback
  deliver-concurrency-emitter-freshness
  deliver-concurrency-docs-presence
  deliver-canonical-state-write
  deliver-terminal-retro-before-pr
  deliver-terminal-autonomous-watch-stabilize
  deliver-terminal-autonomy-knob
  deliver-terminal-no-auto-merge
  cleanup-autonomy-auto-after-merge
  cleanup-autonomy-indeterminate-falls-back
  terminal-autonomy-docs-presence
)

for fx in "${FIXTURES[@]}"; do
  case "$fx" in
    deliver-state-scoped-per-branch)
      if echo "$ALL_OUT" | grep -qE 'OK  deliver-state-scoped-per-branch'; then
        ok "prd-013-fixture-registry:$fx"
      else
        bad "prd-013-fixture-registry:$fx"
      fi
      ;;
    deliver-terminal-autonomy-knob)
      if echo "$ALL_OUT" | grep -qE 'OK  deliver-terminal-autonomy-knob'; then
        ok "prd-013-fixture-registry:$fx"
      else
        bad "prd-013-fixture-registry:$fx"
      fi
      ;;
    deliver-terminal-no-auto-merge)
      if echo "$ALL_OUT" | grep -qE 'OK  deliver-terminal-no-auto-merge'; then
        ok "prd-013-fixture-registry:$fx"
      else
        bad "prd-013-fixture-registry:$fx"
      fi
      ;;
    *)
      if echo "$ALL_OUT" | grep -qE "OK  $fx" || grep -qE "OK  $fx" "$TRACE_FILE" 2>/dev/null; then
        ok "prd-013-fixture-registry:$fx"
      else
        bad "prd-013-fixture-registry:$fx"
      fi
      ;;
  esac
done

if [[ "$FAIL" -eq 0 ]]; then
  echo "prd-013 fixture registry: all scenarios present"
  exit 0
fi
echo "prd-013 fixture registry: failures present"
exit 1
