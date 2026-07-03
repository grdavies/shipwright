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
# In-flight guards emitter/dist parity fixtures (PRD 032 phase 6 — R16).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEN="python3 -m sw"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

GUARD_SCRIPTS=(
  inflight_signal.py
  inflight-signal.py
  inflight_reconcile.py
  inflight-reconcile.py
  clear-inflight.py
  authoring_guard.py
  authoring-guard.py
  inflight_migration_bridge.py
  inflight-migration-bridge.py
)

GUARD_HOOKS=(
  pre-commit-completed-unit.py
)

GUARD_SCHEMAS=(
  inflight-signal.schema.json
  inflight-tuple.schema.json
)

# --- inflight-guards-copy-to-core-parity (R16) ---
if python3 "$ROOT/scripts/copy-to-core.py" >/dev/null 2>&1; then
  :
else
  bad "inflight-guards-copy-to-core-parity: copy-to-core.py failed"
fi

for rel in "${GUARD_SCRIPTS[@]}"; do
  if [[ -f "$ROOT/scripts/$rel" && -f "$ROOT/core/scripts/$rel" ]] && cmp -s "$ROOT/scripts/$rel" "$ROOT/core/scripts/$rel"; then
    :
  else
    bad "inflight-guards-copy-to-core-parity: scripts/$rel not mirrored in core/scripts/"
    break
  fi
done

for rel in "${GUARD_HOOKS[@]}"; do
  if [[ -f "$ROOT/core/hooks/$rel" ]]; then
    :
  else
    bad "inflight-guards-copy-to-core-parity: missing core/hooks/$rel"
  fi
done

if grep -q 'pre-commit-completed-unit' "$ROOT/core/hooks/pre-commit.py" 2>/dev/null; then
  :
else
  bad "inflight-guards-copy-to-core-parity: pre-commit missing completed-unit chain"
fi

for rel in "${GUARD_SCHEMAS[@]}"; do
  if [[ -f "$ROOT/core/sw-reference/$rel" ]]; then
    :
  else
    bad "inflight-guards-copy-to-core-parity: missing core/sw-reference/$rel"
  fi
done

[[ "$FAIL" -eq 0 ]] && ok "inflight-guards-copy-to-core-parity"

# --- inflight-guards-emitter-freshness (R16) ---
$GEN generate --all >/dev/null 2>&1 || bad "inflight-guards-emitter-freshness: generate failed"
HASH1=$(find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
$GEN generate --all >/dev/null 2>&1 || bad "inflight-guards-emitter-freshness: second generate failed"
HASH2=$(find "$ROOT/dist/cursor" "$ROOT/dist/claude-code" -type f -print0 | sort -z | xargs -0 shasum -a 256 | shasum -a 256 | awk '{print $1}')
if [[ "$HASH1" == "$HASH2" ]]; then
  ok "inflight-guards-emitter-freshness: generate idempotent"
else
  bad "inflight-guards-emitter-freshness: generate hash drift"
fi

for dist in "$ROOT/dist/cursor" "$ROOT/dist/claude-code"; do
  for rel in "${GUARD_SCRIPTS[@]}"; do
    if [[ ! -f "$dist/scripts/$rel" ]]; then
      bad "inflight-guards-emitter-freshness: missing $dist/scripts/$rel"
    elif ! cmp -s "$ROOT/core/scripts/$rel" "$dist/scripts/$rel"; then
      bad "inflight-guards-emitter-freshness: drift $dist/scripts/$rel vs core/scripts/$rel"
    fi
  done
  for rel in "${GUARD_HOOKS[@]}"; do
    if [[ ! -f "$dist/core/hooks/$rel" ]]; then
      bad "inflight-guards-emitter-freshness: missing $dist/core/hooks/$rel"
    elif ! cmp -s "$ROOT/core/hooks/$rel" "$dist/core/hooks/$rel"; then
      bad "inflight-guards-emitter-freshness: drift $dist/core/hooks/$rel"
    fi
  done
  for rel in "${GUARD_SCHEMAS[@]}"; do
    if [[ ! -f "$dist/core/sw-reference/$rel" ]]; then
      bad "inflight-guards-emitter-freshness: missing $dist/core/sw-reference/$rel"
    elif ! cmp -s "$ROOT/core/sw-reference/$rel" "$dist/core/sw-reference/$rel"; then
      bad "inflight-guards-emitter-freshness: drift $dist/core/sw-reference/$rel"
    fi
  done
done

if [[ -f "$ROOT/dist/cursor/hooks/pre-commit-completed-unit.py" ]] && \
   cmp -s "$ROOT/core/hooks/pre-commit-completed-unit.py" "$ROOT/dist/cursor/hooks/pre-commit-completed-unit.py"; then
  ok "inflight-guards-emitter-freshness: cursor top-level hook copy"
else
  bad "inflight-guards-emitter-freshness: cursor hooks/pre-commit-completed-unit.py drift"
fi

if git -C "$ROOT" diff --exit-code -- dist/cursor dist/claude-code >/dev/null 2>&1; then
  ok "inflight-guards-emitter-freshness"
else
  bad "inflight-guards-emitter-freshness: committed dist/ drift from generate(core/)"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
