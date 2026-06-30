#!/usr/bin/env python3
"""Normalize ce-code-review JSON to CAPABILITIES contract."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:

    import argparse, json, re, subprocess
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--input"); p.add_argument("--repo-root", default=str(Path.cwd()))
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    if not ns.input:
        print("Usage: code-review-normalize --input PATH", file=sys.stderr); return 2
    inp = Path(ns.input)
    def emit_skip(status, reason):
        print(json.dumps({"status":status,"verdict":"not-ready","reason":reason,"findings":[]})); return 0
    if not inp.is_file(): return emit_skip("failed","input file missing")
    try: data = json.loads(inp.read_text(encoding="utf-8"))
    except json.JSONDecodeError: return emit_skip("failed","malformed JSON from ce-code-review adapter")
    ce_status = data.get("status","failed")
    if ce_status in ("skipped","failed","degraded"): return emit_skip(ce_status, data.get("reason") or "non-finding outcome")
    if ce_status != "complete": return emit_skip("failed", f"unknown ce-code-review status: {ce_status}")
    proc = subprocess.run([sys.executable, str(SCRIPT_DIR/"code_review_normalize_lib.py"), "--input", str(inp), "--repo-root", ns.repo_root], capture_output=True, text=True)
    sys.stdout.write(proc.stdout); return proc.returncode

    return 0

if __name__ == "__main__":
    run_module_main(main)
