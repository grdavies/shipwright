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
# Build-chain SoT fixtures (PRD 038 phase 1 — R3, R12).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FAIL=0
ok() { echo "OK  $1"; }
bad() { echo "FAIL $1"; FAIL=1; }

# --- build-chain-sot-lint (R12) ---
if bash "$ROOT/scripts/build-chain-sot-lint.sh" >/dev/null 2>&1; then
  ok "build-chain-sot-lint"
else
  bad "build-chain-sot-lint"
fi

# --- copy-to-core-orphan-fail-closed (R3) ---
TMP_ORPHAN="$ROOT/core/sw-reference/.fixture-orphan-sot.json"
trap 'rm -f "$TMP_ORPHAN"' EXIT

touch "$TMP_ORPHAN"
if bash "$ROOT/scripts/copy-to-core.sh" >/dev/null 2>&1; then
  bad "copy-to-core-orphan-fail-closed: expected non-zero exit on orphan"
else
  ok "copy-to-core-orphan-fail-closed"
fi
rm -f "$TMP_ORPHAN"

# --- copy-to-core-orphan-force (R16) ---
touch "$TMP_ORPHAN"
if bash "$ROOT/scripts/copy-to-core.sh" --force >/dev/null 2>&1; then
  ok "copy-to-core-orphan-force"
else
  bad "copy-to-core-orphan-force"
fi
rm -f "$TMP_ORPHAN"

# --- copy-to-core-manifest-driven (R4/R13) ---
if bash "$ROOT/scripts/copy-to-core.sh" >/dev/null 2>&1; then
  ok "copy-to-core-manifest-driven"
else
  bad "copy-to-core-manifest-driven"
fi


# --- ci-yml-includes-core-scripts-parity (R5) ---
if grep -q 'test_core_scripts_parity.py' "$ROOT/.github/workflows/ci.yml"; then
  ok "ci-yml-includes-core-scripts-parity"
else
  bad "ci-yml-includes-core-scripts-parity"
fi

# --- verify-test-registers-core-scripts-parity (R6) ---
if python3 -c "
import json
m=json.load(open('$ROOT/core/sw-reference/pr-test-plan.manifest.json'))
ids=[f['id'] for f in m.get('fixtures',[])]
assert 'core-scripts-parity-fixtures' in ids
match=[f for f in m['fixtures'] if f['id']=='core-scripts-parity-fixtures'][0]
assert match['script']=='scripts/test/run_pytest.py'
args=match.get('args') or []
assert any('test_core_scripts_parity' in str(a) or 'unit_tests/meta' in str(a) for a in args)
"; then
  ok "verify-test-registers-core-scripts-parity"
else
  bad "verify-test-registers-core-scripts-parity"
fi


# --- build-chain-sync-runs (R7) ---
if [ -x "$ROOT/scripts/build-chain-sync.sh" ] && bash "$ROOT/scripts/build-chain-sync.sh" >/dev/null 2>&1; then
  ok "build-chain-sync-runs"
else
  bad "build-chain-sync-runs"
fi

# --- build-chain-sync-idempotent (R8) ---
if bash "$ROOT/scripts/build-chain-sync.sh" >/dev/null 2>&1; then
  BEFORE="$(git -C "$ROOT" status --porcelain)"
  if bash "$ROOT/scripts/build-chain-sync.sh" >/dev/null 2>&1; then
    AFTER="$(git -C "$ROOT" status --porcelain)"
    if [ "$BEFORE" = "$AFTER" ]; then
      ok "build-chain-sync-idempotent"
    else
      bad "build-chain-sync-idempotent: second run changed working tree"
    fi
  else
    bad "build-chain-sync-idempotent: second run failed"
  fi
else
  bad "build-chain-sync-idempotent: first run failed"
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
