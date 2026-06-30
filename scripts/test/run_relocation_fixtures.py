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

if bash "$ROOT/scripts/test/run-core-scripts-parity-fixtures.sh"; then
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
if bash "$ROOT/scripts/test/run-hook-fixtures.sh"; then
  echo "OK  hook-fixtures on root layout"
else
  echo "FAIL hook-fixtures on root layout"
  FAIL=1
fi

exit "$FAIL"

"""

if __name__ == "__main__":
    raise SystemExit(main())
