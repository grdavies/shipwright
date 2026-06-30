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
# Assert confirm/auto seed docs-only commit before /sw-deliver run (R80).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
source "$ROOT/scripts/test/fixture-lib.sh"

SW_DOC="$(content_path commands/sw-doc.md)"
FAIL=0

if grep -q 'spec-seed' "$SW_DOC" && \
   grep -q 'docs/prds/<n>-<slug>/' "$SW_DOC" && \
   grep -q '<type>/<slug>' "$SW_DOC" && \
   grep -qi 'idempotent' "$SW_DOC"; then
  echo "OK  doc-afterTasks-seed-confirm-auto: seed commit onto feature branch documented"
else
  echo "FAIL doc-afterTasks-seed-confirm-auto: seed commit contract missing"
  FAIL=1
fi

# confirm: seed before dispatch
if awk '/\*\*`confirm`\*\*/,/\*\*`auto`\*\*/' "$SW_DOC" | grep -q 'spec-seed' && \
   awk '/\*\*`confirm`\*\*/,/\*\*`auto`\*\*/' "$SW_DOC" | grep -q '/sw-deliver run'; then
  echo "OK  doc-afterTasks-seed-confirm-auto: confirm seeds before /sw-deliver run"
else
  echo "FAIL doc-afterTasks-seed-confirm-auto: confirm seed order wrong"
  FAIL=1
fi

# auto: seed before dispatch
if awk '/\*\*`auto`\*\*/,/^14\./' "$SW_DOC" | grep -q 'spec-seed' && \
   awk '/\*\*`auto`\*\*/,/^14\./' "$SW_DOC" | grep -q '/sw-deliver run'; then
  echo "OK  doc-afterTasks-seed-confirm-auto: auto seeds before /sw-deliver run"
else
  echo "FAIL doc-afterTasks-seed-confirm-auto: auto seed order wrong"
  FAIL=1
fi

exit "$FAIL"

"""
if __name__=="__main__": raise SystemExit(main())
