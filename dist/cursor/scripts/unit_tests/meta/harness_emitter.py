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
# Golden tests for sw generate / emitter framework.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX="$ROOT/scripts/test/fixtures/emitter-fixture"
CORE="$FIX/core"
OUT="$FIX/out"
GEN="python3 -m sw"

FAIL=0

rm -rf "$OUT"
mkdir -p "$OUT"

run_expect() {
  local name="$1" expect_ec="$2"
  shift 2
  set +e
  OUT_TEXT=$("$@" 2>&1)
  EC=$?
  set -e
  if [ "$EC" -eq "$expect_ec" ]; then
    echo "OK  $name exit=$EC"
  else
    echo "FAIL $name expected exit=$expect_ec got exit=$EC"
    echo "$OUT_TEXT"
    FAIL=1
  fi
}

# Happy path: fixture core -> cursor dist
run_expect fixture-cursor-generate 0 $GEN generate cursor --core "$CORE" --dest "$OUT"
if [ -f "$OUT/cursor/commands/sw-ship.md" ]; then
  if grep -q 'CURSOR_PLUGIN_ROOT' "$OUT/cursor/commands/sw-ship.md"; then
    echo "OK  fixture-cursor retains CURSOR_PLUGIN_ROOT"
  else
    echo "FAIL fixture-cursor missing CURSOR_PLUGIN_ROOT"
    FAIL=1
  fi
else
  echo "FAIL fixture-cursor missing emitted command"
  FAIL=1
fi

# Claude env substitution
run_expect fixture-claude-generate 0 $GEN generate claude-code --core "$CORE" --dest "$OUT"
if grep -q 'CLAUDE_PLUGIN_ROOT' "$OUT/claude-code/commands/sw-ship.md" 2>/dev/null; then
  echo "OK  fixture-claude env substitution"
else
  echo "FAIL fixture-claude expected CLAUDE_PLUGIN_ROOT in sw-ship.md"
  FAIL=1
fi
if ! grep -q 'CURSOR_PLUGIN_ROOT' "$OUT/claude-code/commands/sw-ship.md" 2>/dev/null; then
  echo "OK  fixture-claude removed CURSOR_PLUGIN_ROOT"
else
  echo "FAIL fixture-claude still contains CURSOR_PLUGIN_ROOT"
  FAIL=1
fi

# R4 refusal: unsupported capability
BAD_DESC='{"platform":"bad","hooks":"wrapper","skills":"native","commands":"slash-md","rules":"mdc","subagents":"native","mcp":"yes","memoryXport":"mcp"}'
run_expect r4-unsupported-hooks 0 python3 -c "
import json, sys, importlib.util
from pathlib import Path
ROOT = Path('$ROOT')
sys.path.insert(0, str(ROOT / 'sw'))
spec = importlib.util.spec_from_file_location('cursor_emitter', ROOT / 'platforms/cursor/emitter.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
from emitter_base import EmitterError
desc = json.loads('''$BAD_DESC''')
try:
    mod.CursorEmitter(desc).validate_descriptor()
    sys.exit(1)
except EmitterError:
    sys.exit(0)
"

# Copy exclusion: __pycache__ not emitted
mkdir -p "$CORE/scripts/__pycache__"
echo 'stale' >"$CORE/scripts/__pycache__/junk.pyc"
run_expect exclude-pycache 0 $GEN generate cursor --core "$CORE" --dest "$OUT"
if [ ! -e "$OUT/cursor/scripts/__pycache__/junk.pyc" ]; then
  echo "OK  fixture excludes __pycache__"
else
  echo "FAIL fixture emitted __pycache__ artifact"
  FAIL=1
fi
rm -rf "$CORE/scripts/__pycache__"

# Idempotence
run_expect idempotent-first 0 $GEN generate cursor --core "$CORE" --dest "$OUT"
HASH1=$(find "$OUT/cursor" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
run_expect idempotent-second 0 $GEN generate cursor --core "$CORE" --dest "$OUT"
HASH2=$(find "$OUT/cursor" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
if [ "$HASH1" = "$HASH2" ]; then
  echo "OK  generate idempotent"
else
  echo "FAIL generate idempotent hash drift"
  FAIL=1
fi

# Real core generate (smoke) — does not require committed dist yet
run_expect real-cursor-smoke 0 $GEN generate cursor --dest "$OUT"
run_expect real-claude-smoke 0 $GEN generate claude-code --dest "$OUT"

# Freshness gate: committed dist/ matches generate(core/)
if [ -d "$ROOT/dist/cursor" ] && [ -d "$ROOT/dist/claude-code" ]; then
  run_expect freshness-generate 0 $GEN generate --all
  if git -C "$ROOT" diff --exit-code -- dist/cursor dist/claude-code >/dev/null 2>&1; then
    echo "OK  freshness dist matches generate(core/)"
    echo "OK  emitter-freshness-007"
  else
    echo "FAIL freshness dist/ drift from generate(core/)"
    git -C "$ROOT" diff --stat -- dist/cursor dist/claude-code || true
    FAIL=1
  fi
fi

# Capability index freshness: stale hand-edited index fails (failing-before / passing-after)
INDEX="$ROOT/core/sw-reference/capability-index.json"
if [ -f "$INDEX" ]; then
  INDEX_BACKUP="$(mktemp)"
  cp "$INDEX" "$INDEX_BACKUP"
  if python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import check_freshness
from pathlib import Path
ok, _ = check_freshness(Path('$ROOT/core'))
sys.exit(0 if ok else 1)
" 2>/dev/null; then
    echo "OK  emitter-freshness-stale-index passing-before"
  else
    echo "FAIL emitter-freshness-stale-index expected fresh index before tamper"
    FAIL=1
  fi
  # Tamper: inject phantom capability row
  python3 -c "
import json
from pathlib import Path
p = Path('$INDEX')
data = json.loads(p.read_text())
data['capabilities'].append({
  'id': 'skill.phantom-stale-fixture',
  'kind': 'skill',
  'sourcePath': 'core/skills/phantom-stale-fixture/SKILL.md',
  'executable': False,
  'capability': {'version': 1, 'triggers': [{'type': 'always_on'}]},
})
p.write_text(json.dumps(data, indent=2) + '\n')
"
  set +e
  python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import check_freshness
from pathlib import Path
ok, _ = check_freshness(Path('$ROOT/core'))
sys.exit(0 if ok else 1)
" >/dev/null 2>&1
  STALE_EC=$?
  set -e
  if [ "$STALE_EC" -ne 0 ]; then
    echo "OK  emitter-freshness-stale-index failing-before"
  else
    echo "FAIL emitter-freshness-stale-index tampered index should fail freshness"
    FAIL=1
  fi
  mv "$INDEX_BACKUP" "$INDEX"
  if python3 -c "
import sys
sys.path.insert(0, '$ROOT/scripts')
from capability_index import check_freshness
from pathlib import Path
ok, _ = check_freshness(Path('$ROOT/core'))
sys.exit(0 if ok else 1)
" 2>/dev/null; then
    echo "OK  emitter-freshness-stale-index passing-after"
  else
    echo "FAIL emitter-freshness-stale-index restored index should pass"
    FAIL=1
  fi
fi

# Kernel/guidelines dist freshness (PRD 022 R24 — emitter-stale-classification-fails)
classification_dist_fresh() {
  local platform="$1"
  local base="$ROOT/dist/$platform/core/sw-reference"
  cmp -s "$ROOT/core/sw-reference/kernel-classification.json" "$base/kernel-classification.json" && \
  cmp -s "$ROOT/core/sw-reference/kernel-classification.md" "$base/kernel-classification.md" && \
  cmp -s "$ROOT/core/sw-reference/guidelines.json" "$base/guidelines.json" && \
  cmp -s "$ROOT/core/sw-reference/guidelines.md" "$base/guidelines.md"
}

if [ -d "$ROOT/dist/cursor/core/sw-reference" ]; then
  if classification_dist_fresh cursor && classification_dist_fresh claude-code; then
    echo "OK  emitter-stale-classification-fails passing-before"
  else
    echo "FAIL emitter-stale-classification-fails expected fresh dist before tamper"
    FAIL=1
  fi
  STALE_DIST="$ROOT/dist/cursor/core/sw-reference/kernel-classification.json"
  STALE_BACKUP="$(mktemp)"
  cp "$STALE_DIST" "$STALE_BACKUP"
  python3 -c "
import json
from pathlib import Path
p = Path('$STALE_DIST')
data = json.loads(p.read_text())
data['kernelVersion'] = 'stale-fixture-tamper'
p.write_text(json.dumps(data, indent=2) + '\n')
"
  if classification_dist_fresh cursor; then
    echo "FAIL emitter-stale-classification-fails tampered dist should fail freshness"
    FAIL=1
  else
    echo "OK  emitter-stale-classification-fails failing-before"
  fi
  mv "$STALE_BACKUP" "$STALE_DIST"
  run_expect emitter-stale-classification-regen 0 $GEN generate --all
  if classification_dist_fresh cursor && classification_dist_fresh claude-code; then
    echo "OK  emitter-stale-classification-fails passing-after"
  else
    echo "FAIL emitter-stale-classification-fails dist should match core after regenerate"
    FAIL=1
  fi
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
