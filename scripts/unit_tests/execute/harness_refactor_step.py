#!/usr/bin/env python3
"""PRD 039 phase-2 refactor step fixtures."""
from __future__ import annotations
import json, subprocess, sys, tempfile
from pathlib import Path

from _sw.vendor_paths import repo_root
SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
ROOT = repo_root(__file__)
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

def ok(m): print(f"OK  {m}")
def bad(m): print(f"FAIL {m}"); return 1

def main() -> int:
    fail = 0
    skill = (ROOT/"core/skills/execute-discipline/SKILL.md").read_text(encoding="utf-8")
    if "tdd-gate → refactor" in skill:
        ok("execute-discipline ordering includes refactor after tdd-gate")
    else:
        fail = bad("execute-discipline ordering") or fail
    simp = (ROOT/"core/skills/simplify/SKILL.md").read_text(encoding="utf-8")
    if "Refactor-vs-simplify boundary" in simp:
        ok("simplify boundary documented")
    else:
        fail = bad("simplify boundary") or fail
    layout = (ROOT/"core/sw-reference/layout.md").read_text(encoding="utf-8")
    if "refactor.metricDelta" in layout:
        ok("layout documents refactor status fields")
    else:
        fail = bad("layout refactor fields") or fail
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"taskRef":"2.1","refactor":{"ran":True,"skipped":False,"verdict":"clean","metricDelta":{}}}, f)
        path = f.name
    proc = subprocess.run([sys.executable, str(ROOT/"scripts/refactor-gate.py"), "--status", path], capture_output=True, text=True)
    if proc.returncode == 0:
        ok("refactor-gate clean pass")
    else:
        fail = bad(f"refactor-gate clean: {proc.stdout}") or fail
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"taskRef":"2.1","refactor":{"ran":False,"skipped":True,"skipReason":""}}, f)
        path2 = f.name
    proc2 = subprocess.run([sys.executable, str(ROOT/"scripts/refactor-gate.py"), "--status", path2], capture_output=True, text=True)
    if proc2.returncode == 20:
        ok("no-silent-skip rejected")
    else:
        fail = bad("no-silent-skip") or fail
  # quality none signal path
    proc3 = subprocess.run([sys.executable, str(ROOT/"scripts/quality_provider.py")], cwd=str(ROOT), capture_output=True, text=True)
    data = json.loads(proc3.stdout)
    if data.get("verdict") == "none":
        ok("quality:none default unchanged")
    else:
        fail = bad(f"quality none: {data}") or fail
    return fail

if __name__ == "__main__":
    raise SystemExit(main())
