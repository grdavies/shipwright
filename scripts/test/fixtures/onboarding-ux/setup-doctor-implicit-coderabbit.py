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
# Assert /sw-setup doctor surfaces implicit-coderabbit migration (R22).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_INIT="$(content_path commands/sw-init.md)"
FAIL=0

if grep -q 'CodeRabbit CLI present but `review.provider` unset' "$SW_INIT" && \
   grep -qi 'migration notice' "$SW_INIT"; then
  echo "OK  setup-doctor-implicit-coderabbit: doctor migration notice documented"
else
  echo "FAIL setup-doctor-implicit-coderabbit: missing implicit-coderabbit doctor notice"
  FAIL=1
fi

if grep -q 'implicit default flipped' "$SW_INIT" || grep -q 'set `review.provider` explicitly' "$SW_INIT"; then
  echo "OK  setup-doctor-implicit-coderabbit: explains explicit provider choice"
else
  echo "FAIL setup-doctor-implicit-coderabbit: missing explicit provider guidance"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
