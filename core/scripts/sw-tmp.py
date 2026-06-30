#!/usr/bin/env python3
"""Per-run private temp dir for evidence files."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:

    import argparse, json, os, shutil, subprocess, time
    import evidence_read as er
    import shipwright_state_lib as ssl
    p = argparse.ArgumentParser()
    p.add_argument("cmd"); p.add_argument("max_age", nargs="?", default="86400")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = SCRIPT_DIR.parent
    if ns.cmd == "init":
        base = Path(os.environ.get("TMPDIR", "/tmp"))
        if not base.is_dir() or base.is_symlink():
            print(json.dumps({"error":"invalid TMPDIR"}), file=sys.stderr); return 2
        import tempfile
        d = Path(tempfile.mkdtemp(prefix="sw-run.", dir=str(base))); d.chmod(0o700)
        if not er.validate_run_dir(d):
            shutil.rmtree(d, ignore_errors=True); print(json.dumps({"error":"invalid run dir"}), file=sys.stderr); return 2
        patch = json.dumps({"runDir": str(d)})
        ssl.cmd_write(Path.cwd(), patch); print(d); return 0
    if ns.cmd == "resolve":
        d = os.environ.get("SW_RUN_DIR","")
        if not d:
            try:
                data = json.loads(subprocess.run([sys.executable, str(SCRIPT_DIR/"shipwright-state.py"), "read"], capture_output=True, text=True).stdout or "{}")
                d = data.get("runDir","")
            except json.JSONDecodeError: d = ""
        print(d); return 0
    if ns.cmd == "clean":
        max_age = int(ns.max_age); base = Path(os.environ.get("TMPDIR","/tmp")); now = time.time(); removed = 0
        if base.is_dir():
            for entry in base.glob("sw-run.*"):
                if entry.is_dir() and not entry.is_symlink() and er.stat_uid(entry) == os.getuid():
                    try:
                        if now - entry.stat().st_mtime > max_age:
                            shutil.rmtree(entry); removed += 1
                    except OSError: pass
        print(json.dumps({"removed": removed})); return 0
    print("usage: sw-tmp init|resolve|clean", file=sys.stderr); return 2

    return 0

if __name__ == "__main__":
    run_module_main(main)
