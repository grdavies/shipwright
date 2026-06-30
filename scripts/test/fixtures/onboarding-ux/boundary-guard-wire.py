#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent.parent))
from _fixture_lib import repo_root

from _harness_patch import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Assert worktree guard wired at implementation entry (R6, R27 task 4.5).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_EXECUTE="$(content_path commands/sw-execute.md)"
SW_START="$(content_path commands/sw-start.md)"
FAIL=0

if grep -q 'sw-assert-worktree.sh' "$SW_EXECUTE"; then
  echo "OK  boundary-guard-wire: sw-execute invokes worktree guard"
else
  echo "FAIL boundary-guard-wire: sw-execute missing sw-assert-worktree"
  FAIL=1
fi

if grep -q 'sw-assert-worktree.sh' "$SW_START"; then
  echo "OK  boundary-guard-wire: sw-start invokes worktree guard"
else
  echo "FAIL boundary-guard-wire: sw-start missing sw-assert-worktree"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
