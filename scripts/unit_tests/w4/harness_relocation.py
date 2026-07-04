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
# Verify core/ additive copies match the live root layout and golden manifest coverage.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CORE="$ROOT/core"
GOLDEN="$ROOT/scripts/test/fixtures/parity/cursor-golden.manifest"
COMPARE="$ROOT/scripts/test/parity-compare.sh"

FAIL=0

if [ ! -d "$CORE" ]; then
  echo "FAIL core/ directory missing — run scripts/copy-to-core.sh"
  exit 1
fi

if python3 "$ROOT/scripts/unit_tests/meta/harness_core_scripts_parity.py" >/dev/null 2>&1; then
  echo "OK  core-scripts-parity wired"
else
  echo "FAIL core-scripts-parity"
  FAIL=1
fi

# Every golden manifest path must exist under core/ with identical hash.
while IFS=$'\t' read -r path hash; do
  [ -n "$path" ] || continue
  core_file="$CORE/$path"
  if [ ! -f "$core_file" ]; then
    echo "FAIL relocation-coverage missing core/$path"
    FAIL=1
    continue
  fi
  core_hash="$(shasum -a 256 "$core_file" | awk '{print $1}')"
  if [ "$core_hash" != "$hash" ]; then
    echo "FAIL relocation-hash core/$path differs from golden manifest"
    FAIL=1
  fi
done <"$GOLDEN"

if [ "$FAIL" -eq 0 ]; then
  echo "OK  relocation-coverage all golden paths present in core/ with matching hashes"
fi

# dist/cursor matches golden manifest; root layout is no longer the install source post-flip.
if bash "$COMPARE" "$ROOT/dist/cursor" "$GOLDEN"; then
  echo "OK  dist/cursor parity matches golden manifest"
else
  echo "FAIL dist/cursor parity"
  FAIL=1
fi

# Existing hook fixtures still pass on root-loaded plugin.
if python3 "$ROOT/scripts/unit_tests/hooks/harness_hook.py" >/dev/null 2>&1; then
  echo "OK  hook-fixtures on root layout"
else
  echo "FAIL hook-fixtures on root layout"
  FAIL=1
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
