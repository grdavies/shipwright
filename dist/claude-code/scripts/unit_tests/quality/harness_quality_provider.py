#!/usr/bin/env python3
"""PRD 039 phase-1 quality harness fixtures."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

from _fixture_lib import repo_root
SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
ROOT = repo_root(__file__)
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

def ok(msg): print(f"OK  {msg}")
def bad(msg): print(f"FAIL {msg}"); return 1

def main() -> int:
    fail = 0
    proc = subprocess.run([sys.executable, str(ROOT/"scripts/quality_provider.py")], cwd=str(ROOT), capture_output=True, text=True)
    if proc.returncode != 0:
        fail = bad("none-default-exit") or fail
    else:
        data = json.loads(proc.stdout)
        if data.get("verdict") == "none" and data.get("provider") == "none":
            ok("none default proceeds unchanged (quality:none)")
        else:
            fail = bad(f"none-default-verdict: {data}") or fail
    schema = ROOT/"core/sw-reference/quality-signal.schema.json"
    if schema.is_file() and '"verdict"' in schema.read_text(encoding="utf-8"):
        ok("quality-signal schema present")
    else:
        fail = bad("quality-signal schema missing") or fail
    from quality_config_freeze import pin_from_config, validate_pin
    pin = pin_from_config({"quality": {"provider": "none"}})
    if validate_pin(pin, {"quality": {"provider": "none"}}).get("verdict") == "pass":
        ok("config freeze pass on unchanged slice")
    else:
        fail = bad("config freeze unchanged") or fail
    if validate_pin(pin, {"quality": {"provider": "auto"}}).get("verdict") == "fail":
        ok("config mutation mid-run fails")
    else:
        fail = bad("config freeze mutation") or fail
    caps = ROOT/"scripts/capability_trust.py"
    if "quality" in caps.read_text(encoding="utf-8"):
        ok("capability_trust registers quality.provider")
    else:
        fail = bad("capability_trust quality") or fail
    return fail

if __name__ == "__main__":
    raise SystemExit(main())
