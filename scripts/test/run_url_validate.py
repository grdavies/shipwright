#!/usr/bin/env python3
"""Ported harness (R27)."""
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
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHONPATH="$ROOT" python3 <<'PY'
from hooks.sw_recallium_url import is_allowed_recallium_base

assert is_allowed_recallium_base("http://localhost:8001")
assert is_allowed_recallium_base("http://127.0.0.1:8001")
assert not is_allowed_recallium_base("http://169.254.169.254/")
assert not is_allowed_recallium_base("file:///etc/passwd")
print("OK  recallium URL validation")
PY

"""
if __name__=="__main__": raise SystemExit(main())
