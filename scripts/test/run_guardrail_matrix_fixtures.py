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
# Cross-platform guardrail enforcement matrix (Cursor + Claude Code adapters).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX="$ROOT/scripts/test/fixtures/guardrail-matrix"

echo "guardrail-matrix: driving shared scenarios (see $FIX/README.md)"

if bash "$ROOT/scripts/test/run-hook-fixtures.sh"; then
  echo "OK  guardrail-matrix cursor+claude shared scenarios"
else
  echo "FAIL guardrail-matrix hook scenarios"
  exit 1
fi

exit 0

"""

if __name__ == "__main__":
    raise SystemExit(main())
