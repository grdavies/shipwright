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
# PRD 034 Phase 4 — provision-time materialization + commit-boundary barrier fixtures.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export PYTHONPATH="$ROOT/scripts:${PYTHONPATH:-}"
PY="$ROOT/scripts/planning_materialize.py"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }
TMP="$(mktemp -d)"
CFG_BACKUP=""
if [[ -f "$ROOT/.cursor/workflow.config.json" ]]; then
  CFG_BACKUP="$TMP/workflow.config.json.bak"
  cp "$ROOT/.cursor/workflow.config.json" "$CFG_BACKUP"
fi
restore_config() {
  if [[ -n "$CFG_BACKUP" ]]; then
    cp "$CFG_BACKUP" "$ROOT/.cursor/workflow.config.json"
  else
    rm -f "$ROOT/.cursor/workflow.config.json"
  fi
}
trap 'restore_config; rm -rf "$TMP" "$ROOT/docs/prds/_fixture-materialize"' EXIT

write_in_repo_public_config() {
  python3 - <<PY
import json
from pathlib import Path
backup = Path("$CFG_BACKUP")
live = Path("$ROOT/.cursor/workflow.config.json")
if backup.is_file():
    cfg = json.loads(backup.read_text(encoding="utf-8"))
elif live.is_file():
    cfg = json.loads(live.read_text(encoding="utf-8"))
else:
    cfg = {"version": 1}
cfg.setdefault("planning", {}).setdefault("store", {})["backend"] = "in-repo-public"
live.parent.mkdir(parents=True, exist_ok=True)
live.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
PY
}

# --- materialize-provision-backend-pinned ---
write_in_repo_public_config
mkdir -p "$ROOT/docs/prds/_fixture-materialize"
cat >"$ROOT/docs/prds/_fixture-materialize/099-fixture-private-prd.md" <<'EOF'
---
id: fixture-private-prd
type: prd
status: proposed
title: Private fixture PRD
visibility: private
---
# private fixture body GOLDEN_PRIVATE_SPEC_BODY
EOF
cat >"$ROOT/docs/prds/_fixture-materialize/tasks-099-fixture-private.md" <<'EOF'
---
frozen: true
prd: 099-fixture-private-prd.md
---
# Tasks

### 4. Fixture phase
EOF
WT="$TMP/phase-worktree"
mkdir -p "$WT"
TARGET_BRANCH="feat/planning-feedback-lifecycle"
STATE="$ROOT/.cursor/sw-deliver-state.planning-feedback-lifecycle.json"
STATE_BACKUP="$TMP/state-backup.json"
if [[ -f "$STATE" ]]; then
  cp "$STATE" "$STATE_BACKUP"
fi
cat >"$STATE" <<EOF
{
  "target": {"branch": "$TARGET_BRANCH"}
}
EOF
export SW_FORCE_MATERIALIZE=1
if OUT=$(python3 "$PY" --root "$ROOT" provision \
  --worktree "$WT" \
  --task-list "docs/prds/_fixture-materialize/tasks-099-fixture-private.md" \
  --target "$TARGET_BRANCH" 2>/dev/null); then
  DEST="$WT/.cursor/planning-materialized/docs/prds/_fixture-materialize/099-fixture-private-prd.md"
  if [[ -f "$DEST" ]] && grep -q 'GOLDEN_PRIVATE_SPEC_BODY' "$DEST"; then
    ok "materialize-provision-backend-pinned:provision-copy"
  else
    bad "materialize-provision-backend-pinned:provision-copy"
  fi
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('backend')"; then
    ok "materialize-provision-backend-pinned:backend-pinned"
  else
    bad "materialize-provision-backend-pinned:backend-pinned"
  fi
else
  echo "$OUT" >&2
  bad "materialize-provision-backend-pinned:provision"
fi
if OUT=$(python3 "$PY" --root "$ROOT" validate-pin 2>&1); then
  if echo "$OUT" | python3 -c "import json,sys; assert json.load(sys.stdin).get('verdict')=='ok'"; then
    ok "materialize-provision-backend-pinned:validate-pin"
  else
    bad "materialize-provision-backend-pinned:validate-pin"
  fi
else
  bad "materialize-provision-backend-pinned:validate-pin"
fi
PIN_CFG_BACKUP="$TMP/workflow.config.pinned.json"
cp "$ROOT/.cursor/workflow.config.json" "$PIN_CFG_BACKUP"
python3 - <<PY
import json
from pathlib import Path
p = Path("$ROOT/.cursor/workflow.config.json")
cfg = json.loads(p.read_text()) if p.is_file() else {"version": 1}
planning = cfg.setdefault("planning", {})
store = planning.setdefault("store", {})
store["backend"] = "memory"
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text(json.dumps(cfg, indent=2) + "\n")
PY
if OUT=$(python3 "$PY" --root "$ROOT" validate-pin 2>&1); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail' and d.get('halt')=='backend-swap'"; then
    ok "materialize-provision-backend-pinned:backend-swap-halt"
  else
    echo "$OUT" >&2
    bad "materialize-provision-backend-pinned:backend-swap-halt"
  fi
else
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail' and d.get('halt')=='backend-swap'"; then
    ok "materialize-provision-backend-pinned:backend-swap-halt"
  else
    echo "$OUT" >&2
    bad "materialize-provision-backend-pinned:backend-swap-halt"
  fi
fi
if [[ -f "$PIN_CFG_BACKUP" ]]; then
  cp "$PIN_CFG_BACKUP" "$ROOT/.cursor/workflow.config.json"
else
  write_in_repo_public_config
fi
if [[ -f "$STATE_BACKUP" ]]; then
  cp "$STATE_BACKUP" "$STATE"
else
  rm -f "$STATE"
fi
unset SW_FORCE_MATERIALIZE

if OUT=$(SW_SKIP_MATERIALIZE=1 python3 "$PY" --root "$ROOT" provision \
  --worktree "$WT" \
  --task-list "docs/prds/_fixture-materialize/tasks-099-fixture-private.md" 2>&1); then
  if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='skipped'"; then
    ok "materialize-provision-backend-pinned:ci-host-skip"
  else
    bad "materialize-provision-backend-pinned:ci-host-skip"
  fi
else
  bad "materialize-provision-backend-pinned:ci-host-skip"
fi

# --- commit-boundary-barrier ---
HOOK_ROOT="$TMP/hook-repo"
git init -q "$HOOK_ROOT"
git -C "$HOOK_ROOT" config user.email "fixture@test"
git -C "$HOOK_ROOT" config user.name "Fixture"
echo "# fixture" >"$HOOK_ROOT/README.md"
echo ".cursor/planning-materialized/" >>"$HOOK_ROOT/.gitignore"
git -C "$HOOK_ROOT" add README.md .gitignore
git -C "$HOOK_ROOT" commit -q -m "init"
mkdir -p "$HOOK_ROOT/.cursor/planning-materialized/private"
echo "secret body" >"$HOOK_ROOT/.cursor/planning-materialized/private/body.md"
git -C "$HOOK_ROOT" add -f ".cursor/planning-materialized/private/body.md" 2>/dev/null || true
if python3 "$PY" --root "$HOOK_ROOT" guard-staged 2>/dev/null; then
  bad "commit-boundary-barrier:git-add-f-not-rejected"
else
  ok "commit-boundary-barrier:git-add-f-rejected"
fi
git -C "$HOOK_ROOT" reset -q HEAD 2>/dev/null || true
git -C "$HOOK_ROOT" checkout -q -- . 2>/dev/null || true
echo "[redacted:private-body]" >"$HOOK_ROOT/leak.md"
git -C "$HOOK_ROOT" add leak.md
git -C "$HOOK_ROOT" commit -q -m "leak"
OUT=$(python3 "$PY" --root "$HOOK_ROOT" scan-diff --base HEAD~1 2>/dev/null || true)
if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail' and d.get('markerPaths')"; then
  ok "commit-boundary-barrier:diff-scan-marker"
else
  echo "$OUT" >&2
  bad "commit-boundary-barrier:diff-scan-marker"
fi
mkdir -p "$HOOK_ROOT/.cursor/planning-materialized/x"
echo x >"$HOOK_ROOT/.cursor/planning-materialized/x/b.md"
git -C "$HOOK_ROOT" add -f ".cursor/planning-materialized/x/b.md"
git -C "$HOOK_ROOT" commit -q -m "prefix-leak"
OUT=$(python3 "$PY" --root "$HOOK_ROOT" scan-diff --base HEAD~1 2>/dev/null || true)
if echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d.get('verdict')=='fail' and d.get('prefixPaths')"; then
  ok "commit-boundary-barrier:diff-scan-prefix"
else
  bad "commit-boundary-barrier:diff-scan-prefix"
fi

exit $FAIL

"""

if __name__ == "__main__":
    raise SystemExit(main())
