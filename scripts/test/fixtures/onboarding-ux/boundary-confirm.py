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
# Assert confirm mode strict ack and Go/silence → stop (R2, R3).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -qE '\*\*`proceed`\*\*|\*\*proceed\*\*' "$SW_DOC" && grep -qE '\*\*`yes`\*\*|\*\*yes\*\*' "$SW_DOC"; then
  echo "OK  boundary-confirm: strict proceed/yes tokens documented"
else
  echo "FAIL boundary-confirm: missing proceed/yes ack contract"
  FAIL=1
fi

if grep -q '`Go`' "$SW_DOC" && grep -qi 'stop' "$SW_DOC"; then
  echo "OK  boundary-confirm: legacy Go maps to stop"
else
  echo "FAIL boundary-confirm: Go → stop mapping missing"
  FAIL=1
fi

if grep -qi 'silence' "$SW_DOC" && grep -qi 'ambiguous' "$SW_DOC"; then
  echo "OK  boundary-confirm: silence/ambiguous → stop"
else
  echo "FAIL boundary-confirm: silence/ambiguous stop behavior missing"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
