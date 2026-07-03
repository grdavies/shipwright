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
# Cross-platform guardrail enforcement matrix (Cursor + Claude Code adapters).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FIX="$ROOT/scripts/test/fixtures/guardrail-matrix"

echo "guardrail-matrix: driving shared scenarios (see $FIX/README.md)"

if python3 "$ROOT/scripts/unit_tests/hooks/harness_hook.py"; then
  echo "OK  guardrail-matrix cursor+claude shared scenarios"
else
  echo "FAIL guardrail-matrix hook scenarios"
  exit 1
fi

exit 0

"""

if __name__ == "__main__":
    raise SystemExit(main())
