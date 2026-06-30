#!/usr/bin/env python3
"""Ported fixture helper (R27)."""
from __future__ import annotations
import os, re, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))
from _fixture_lib import repo_root

from _harness_patch import patch_source as _patch_source

def main() -> int:
    root = repo_root(__file__)
    env = os.environ.copy(); env['ROOT']=str(root)
    env['PYTHONPATH']=str(root/'scripts')+os.pathsep+env.get('PYTHONPATH','')
    return subprocess.run(['bash','-c',_patch_source(_SOURCE,root)],cwd=str(root),env=env,shell=False).returncode
_SOURCE = r"""
#!/usr/bin/env bash
# Assert confirm dispatch invokes /sw-deliver run, not legacy chain (R76).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`confirm`\*\*' "$SW_DOC" && \
   grep -q '/sw-deliver run <frozen-task-list-path>' "$SW_DOC"; then
  echo "OK  doc-afterTasks-confirm-deliver: confirm dispatches /sw-deliver run"
else
  echo "FAIL doc-afterTasks-confirm-deliver: confirm missing /sw-deliver run dispatch"
  FAIL=1
fi

if grep -q 'Do \*\*not\*\* recommend `/sw-worktree`' "$SW_DOC" || \
   grep -q 'Do \*\*not\*\* recommend' "$SW_DOC"; then
  echo "OK  doc-afterTasks-confirm-deliver: legacy chain not primary path"
else
  echo "FAIL doc-afterTasks-confirm-deliver: missing legacy-chain non-primary guard"
  FAIL=1
fi

if ! grep -q 'confirm.*`/sw-worktree`.*dispatch' "$SW_DOC" 2>/dev/null; then
  echo "OK  doc-afterTasks-confirm-deliver: confirm does not dispatch worktree chain"
else
  echo "FAIL doc-afterTasks-confirm-deliver: confirm still dispatches legacy chain"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
