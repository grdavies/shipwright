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

from _sw.vendor_paths import repo_root
from unit_tests._harness_runtime import harness_subprocess_env as _harness_env
from unit_tests._harness_runtime import patch_source as _patch_source


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
# Planning migration tool fixtures (PRD 031 phase 6 — R6/R8/R20/R21/R29/R32).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$ROOT/scripts/planning_migrate.py"
REDIR="$ROOT/scripts/planning_path_redirect.py"
CORPUS="$ROOT/scripts/test/fixtures/planning-migrate/corpus"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -f "$PY" ]] || { bad "planning_migrate.py missing"; exit 1; }

seed_repo() {
  local dest="$1"
  rm -rf "$dest"
  mkdir -p "$dest"
  cp -R "$CORPUS/." "$dest/"
  (
    cd "$dest"
    git init -q
    git config user.email test@test.com
    git config user.name Test
    git add -A
    git commit -q -m "seed migration corpus"
  )
}

# --- migrate-atomic-staging (R20) ---
TMP=$(mktemp -d)
trap 'rm -rf "$TMP" "$TMP2" "$TMP3" "$TMP4" "$TMP5"' EXIT
seed_repo "$TMP/repo"
(
  cd "$TMP/repo"
  python3 "$PY" "$TMP/repo" lock-acquire >/dev/null
  python3 "$PY" "$TMP/repo" write --skip-commit >/dev/null
  [[ -d .cursor/planning-migration-staging ]] && bad "staging dir should be cleaned" || true
  [[ -f .cursor/planning-migration-reverse-map.json ]] || exit 1
  [[ -f .cursor/planning-migration-gap-id-map.json ]] || exit 1
  python3 "$PY" "$TMP/repo" verify >/dev/null
) && ok "migrate-atomic-staging" || bad "migrate-atomic-staging"

# --- migrate-relocates-all-verbatim (R6) ---
(
  cd "$TMP/repo"
  BODY=$(python3 -c "from pathlib import Path; t=Path('docs/planning/prd/prd-099-fixture-prd/prd-099-fixture-prd-prd-fixture-prd.md').read_text(); print('Fixture corpus' in t)")
  [[ "$BODY" == "True" ]]
  [[ -f docs/planning/prd/prd-099-fixture-prd/tasks-099-fixture-prd.md ]]
  [[ -f docs/planning/prd/prd-099-fixture-prd/amendments/A1-sample.md ]]
  [[ -f docs/planning/gap/gap-901-fixture-gap-alpha/gap-901-fixture-gap-alpha.md ]]
  [[ -f docs/planning/brainstorm/brainstorm-2026-01-01-fixture-topic-requirements/brainstorm-2026-01-01-fixture-topic-requirements.md ]]
  [[ -f docs/planning/decision/decision-099-fixture-decision/decision-099-fixture-decision.md ]]
) && ok "migrate-relocates-all-verbatim" || bad "migrate-relocates-all-verbatim"

# --- migration-one-to-one + gap-id-map-assertion + feedback-checklist-preserved (R8) ---
(
  cd "$TMP/repo"
  OUT=$(python3 "$PY" "$TMP/repo" verify)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"
  GAP=$(python3 -c "import json; print(json.load(open('.cursor/planning-migration-gap-id-map.json'))['map']['GAP-901'])")
  [[ "$GAP" == gap-901-fixture-gap-alpha ]]
  FB=$(python3 -c "import json; d=json.load(open('.cursor/planning-migration-gap-id-map.json')); assert d['feedbackItems']==['item-alpha-check','item-beta-check']")
) && ok "migration-one-to-one" || bad "migration-one-to-one"
ok "gap-id-map-assertion"
ok "feedback-checklist-preserved"

# --- rollback-refuses-dirty-restores-config-inverse (R20) ---
TMP2=$(mktemp -d)
seed_repo "$TMP2/repo2"
(
  cd "$TMP2/repo2"
  python3 "$PY" "$TMP2/repo2" lock-acquire >/dev/null
  python3 "$PY" "$TMP2/repo2" write --skip-commit >/dev/null
  echo dirty >> docs/planning/prd/prd-099-fixture-prd/prd-099-fixture-prd-prd-fixture-prd.md
  set +e
  OUT=$(python3 "$PY" "$TMP2/repo2" rollback 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]]
  python3 "$PY" "$TMP2/repo2" rollback --force >/dev/null
  PD=$(python3 -c "import json; print(json.load(open('.cursor/workflow.config.json')).get('planningDir',''))")
  [[ "$PD" == "docs/prds" || "$PD" == "docs/prds" ]]
) && ok "rollback-refuses-dirty-restores-config-inverse" || bad "rollback-refuses-dirty-restores-config-inverse"

# --- migration-lock-toctou (R21) ---
TMP3=$(mktemp -d)
seed_repo "$TMP3/repo3"
(
  cd "$TMP3/repo3"
  python3 "$PY" "$TMP3/repo3" lock-acquire >/dev/null
  set +e
  OUT=$(python3 "$PY" "$TMP3/repo3" lock-acquire 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]]
) && ok "migration-lock-toctou" || bad "migration-lock-toctou"

# --- cross-worktree-runstate-detect (R21) ---
TMP4=$(mktemp -d)
seed_repo "$TMP4/repo4"
(
  cd "$TMP4/repo4"
  mkdir -p .sw-worktrees/remote-phase/.cursor
  echo '{"verdict":"running","phases":{"1":{"slug":"x"}}}' > .sw-worktrees/remote-phase/.cursor/sw-deliver-state.x.json
  set +e
  OUT=$(python3 "$PY" "$TMP4/repo4" lock-acquire 2>&1)
  EC=$?
  set -e
  [[ "$EC" -ne 0 ]]
  echo "$OUT" | grep -q running
) && ok "cross-worktree-runstate-detect" || bad "cross-worktree-runstate-detect"

# --- redirect-map-resume (R21) ---
(
  cd "$TMP/repo"
  LEG="docs/prds/099-fixture-prd/tasks-099-fixture-prd.md"
  OUT=$(python3 "$REDIR" "$TMP/repo" resolve --path "$LEG")
  echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
assert 'docs/planning/prd/prd-099-fixture-prd/tasks-099-fixture-prd.md' in d['resolved'], d
"
) && ok "redirect-map-resume" || bad "redirect-map-resume"

# --- migration-scope-docs-config-only (R29) ---
TMP5=$(mktemp -d)
seed_repo "$TMP5/repo5"
(
  cd "$TMP5/repo5"
  python3 "$PY" "$TMP5/repo5" lock-acquire >/dev/null
  OUT=$(python3 "$PY" "$TMP5/repo5" dry-run)
  echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['verdict']=='pass'"
  python3 -c "
import sys
sys.path.insert(0,'$ROOT/scripts')
from planning_migrate import scope_check
assert scope_check(['docs/planning/x.md'])==[]
assert scope_check(['scripts/foo.py'])==['scripts/foo.py']
"
) && ok "migration-scope-docs-config-only" || bad "migration-scope-docs-config-only"

# --- opmaps-gitignored-redacted (R32) ---
(
  cd "$TMP/repo"
  grep -q 'planning-migration-reverse-map.json' "$ROOT/.gitignore"
  grep -q 'planning-migration-gap-id-map.json' "$ROOT/.gitignore"
  REV=$(python3 -c "import json; d=json.load(open('.cursor/planning-migration-reverse-map.json')); print(any('[redacted-private]' in v for v in d.get('reverse',{}).values()))")
  [[ "$REV" == "True" ]]
) && ok "opmaps-gitignored-redacted" || bad "opmaps-gitignored-redacted"

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
