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
# Assert guides name /sw-deliver run for stop/confirm/auto (R78).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
FAIL=0

check_guide() {
  local label="$1" path="$2"
  if [[ ! -f "$path" ]]; then
    echo "FAIL doc-afterTasks-guides-deliver: missing $label"
    FAIL=1
    return
  fi
  local body
  body="$(cat "$path")"
  if echo "$body" | grep -q '/sw-deliver run' && \
     echo "$body" | grep -qE '`stop`|stop' && \
     echo "$body" | grep -qE '`confirm`|confirm' && \
     echo "$body" | grep -qE '`auto`|auto'; then
    echo "OK  doc-afterTasks-guides-deliver: $label documents /sw-deliver run for stop/confirm/auto"
  else
    echo "FAIL doc-afterTasks-guides-deliver: $label missing /sw-deliver run for all modes"
    FAIL=1
  fi
}

check_guide configuration "$ROOT/docs/guides/configuration.md"
check_guide getting-started "$ROOT/docs/guides/getting-started.md"

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
