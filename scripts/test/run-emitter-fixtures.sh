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
  else
    echo "FAIL freshness dist/ drift from generate(core/)"
    git -C "$ROOT" diff --stat -- dist/cursor dist/claude-code || true
    FAIL=1
  fi
fi

exit "$FAIL"
