#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
from _sw.vendor_paths import repo_root

from unit_tests._harness_runtime import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Assert full build chain regen: core/scripts sync, dist freshness, parity golden (R13).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
FAIL=0

if [[ -f "$ROOT/core/scripts/sw-assert-worktree.py" ]]; then
  echo "OK  build-chain-regen: sw-assert-worktree synced to core/scripts"
else
  echo "FAIL build-chain-regen: core/scripts/sw-assert-worktree.py missing"
  FAIL=1
fi

if [[ -f "$ROOT/scripts/check-frozen.py" ]] && [[ ! -f "$ROOT/core/scripts/check-frozen.py" ]]; then
  echo "OK  build-chain-regen: check-frozen harness at scripts/ root only (not emitted)"
else
  echo "FAIL build-chain-regen: check-frozen should be root harness only, not in core/scripts"
  FAIL=1
fi

bash "$ROOT/scripts/test/run-emitter-fixtures.sh" || FAIL=1
bash "$ROOT/scripts/test/run-parity-fixtures.sh" || FAIL=1

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
