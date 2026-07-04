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
# Assert stop is print-only with seed commit + /sw-deliver run; never onto main (R82).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q 'spec-seed' "$SW_DOC" && grep -qi 'print-only' "$SW_DOC" && \
   grep -q '/sw-deliver run' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-stop: stop prints seed + deliver commands"
else
  echo "FAIL doc-afterTasks-seed-stop: stop missing seed + deliver print guidance"
  FAIL=1
fi

if grep -q 'never onto `main`' "$SW_DOC" || grep -q 'never onto .main.' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-stop: stop never directs spec onto main"
else
  echo "FAIL doc-afterTasks-seed-stop: stop must not seed onto main"
  FAIL=1
fi

if grep -q 'spec-seed' "$SW_DOC" && grep -q 'docs/prds/<n>-<slug>/' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-stop: stop prints spec-seed onto feature branch"
else
  echo "FAIL doc-afterTasks-seed-stop: stop missing spec-seed command"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
