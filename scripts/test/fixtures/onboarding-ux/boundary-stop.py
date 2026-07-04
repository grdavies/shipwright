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
# Assert stop mode halts with task-list path + next commands (R4).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q '\*\*`stop`\*\*' "$SW_DOC" && grep -qi 'halt' "$SW_DOC" && \
   grep -q '/sw-deliver run' "$SW_DOC" && grep -q 'docs-only seed' "$SW_DOC"; then
  echo "OK  boundary-stop: stop halts with seed + /sw-deliver run"
else
  echo "FAIL boundary-stop: missing stop halt + deliver handoff"
  FAIL=1
fi

if grep -qi 'no implementation dispatch' "$SW_DOC" || grep -qi 'No implementation' "$SW_DOC"; then
  echo "OK  boundary-stop: stop does not dispatch implementation"
else
  echo "FAIL boundary-stop: stop must not dispatch implementation"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
