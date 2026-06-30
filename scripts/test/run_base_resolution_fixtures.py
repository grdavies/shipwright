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
# Fixtures for PRD 018 Phase 3 — base-branch resolution + fail-closed leak fixes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESOLVE="$ROOT/scripts/resolve-base-branch.sh"
PY="$ROOT/scripts/resolve_base_branch.py"
FAIL=0

ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

[[ -x "$RESOLVE" ]] || { bad "resolve-base-branch.sh missing"; exit 1; }

FIX=$(mktemp -d)
trap 'rm -rf "$FIX"' EXIT

setup_repo() {
  cd "$FIX/repo"
  git init -q
  git config user.email test@test.com
  git config user.name Test
  echo init > README.md
  git add README.md
  git commit -q -m init
  git branch -M main
  git checkout -q -b dev
  echo dev >> README.md
  git add README.md
  git commit -q -m dev
}

mkdir -p "$FIX/repo"
setup_repo

# --- base-resolution-precedence: captured HEAD on dev when schema default is main ---
cd "$FIX/repo"
rm -f .cursor/sw-base-state.json
if OUT=$(bash "$RESOLVE" capture 2>/dev/null) && echo "$OUT" | python3 -c "
import json,sys
d=json.load(sys.stdin)
t=d.get('trunkBase',{})
assert t.get('name')=='dev', t.get('name')
assert t.get('source')=='captured-from-head', t.get('source')
"; then
  ok "base-resolution-precedence"
else
  bad "base-resolution-precedence"
fi

# --- base-persist-name-and-sha ---
if [[ -f "$FIX/repo/.cursor/sw-base-state.json" ]] && python3 - "$FIX/repo/.cursor/sw-base-state.json" <<'PY'
import json,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text())
t=d["trunkBase"]
assert t.get("name") and t.get("sha") and len(t["sha"])>=7
PY
then
  ok "base-persist-name-and-sha"
else
  bad "base-persist-name-and-sha"
fi

# --- base-entry-guard-actionable ---
cd "$FIX/repo"
git checkout -q -b feat/demo-work
set +e
OUT=$(bash "$RESOLVE" capture 2>&1)
EC=$?
set -e
if [[ "$EC" -ne 0 ]] && echo "$OUT" | grep -qi 'work branch'; then
  ok "base-entry-guard-actionable"
else
  bad "base-entry-guard-actionable"
fi

# --- base-disclosed-at-entry ---
cd "$FIX/repo"
git checkout -q dev
bash "$RESOLVE" capture --force >/dev/null 2>&1
if LINE=$(bash "$RESOLVE" disclose --quiet 2>/dev/null) && echo "$LINE" | grep -q '^base: dev'; then
  ok "base-disclosed-at-entry"
else
  bad "base-disclosed-at-entry"
fi

# --- base-resume-needs-replay ---
rm -f "$FIX/repo/.cursor/sw-base-state.json"
set +e
bash "$RESOLVE" disclose >/dev/null 2>&1
EC=$?
set -e
if [[ "$EC" -ne 0 ]]; then
  ok "base-resume-needs-replay"
else
  bad "base-resume-needs-replay"
fi

# --- frozen-secretscan-failclosed wiring ---
if grep -q 'resolve-base-branch' "$ROOT/scripts/check-frozen.sh" && \
   grep -q 'resolve_base_branch' "$ROOT/scripts/secret_scan.py"; then
  ok "frozen-secretscan-failclosed"
else
  bad "frozen-secretscan-failclosed"
fi

# --- lifecycle-base-fallback ---
if grep -q 'resolve_base_branch' "$ROOT/scripts/wave_lifecycle.py"; then
  ok "lifecycle-base-fallback"
else
  bad "lifecycle-base-fallback"
fi

# --- base-drives-fork-and-pr ---
if grep -q 'load_trunk_base\|resolve_base_branch' "$ROOT/scripts/wave_spec_seed.py" && \
   grep -q 'resolve_base_branch' "$ROOT/scripts/wave_terminal.py"; then
  ok "base-drives-fork-and-pr"
else
  bad "base-drives-fork-and-pr"
fi

# --- deliver-loop base-capture ---
if grep -q 'base-capture' "$ROOT/scripts/wave_deliver_loop.py"; then
  ok "deliver-base-capture"
else
  bad "deliver-base-capture"
fi

# --- prose-base-generalized (docs reference resolve-base-branch) ---
if grep -q 'resolve-base-branch' "$ROOT/core/commands/sw-start.md" && \
   grep -q 'resolve-base-branch' "$ROOT/core/commands/sw-worktree.md"; then
  ok "prose-base-generalized"
else
  bad "prose-base-generalized"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
