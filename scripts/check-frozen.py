#!/usr/bin/env python3
"""Reject diffs that modify frozen artifacts. CI authority for doc-freeze integrity (R9)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd().resolve()
    if args and args[0] == "freeze-commit":
        artifact = ""
        i = 1
        while i < len(args):
            if args[i] == "--artifact" and i+1 < len(args): artifact = args[i+1]; i += 2
            else: print(json.dumps({"verdict":"fail","reason":"unknown arg"}), file=sys.stderr); return 2
        if not artifact:
            print(json.dumps({"verdict":"fail","reason":"--artifact required"}), file=sys.stderr); return 2
        from primary_checkout_guard import enforce_guard
        from wave_spec_seed import resolve_target_from_artifact
        branch, _slug, _docs = resolve_target_from_artifact(root, artifact)
        enforce_guard(root, branch)
        import planning_visibility as planning_vis
        vis = planning_vis.check_tracked_public_at_freeze(root, root / artifact)
        if vis.get("verdict") == "fail":
            print(json.dumps({"verdict": "fail", "action": "freeze-commit", **vis}), file=sys.stderr)
            return 20
        proc = subprocess.run([sys.executable, str(SCRIPT_DIR/"wave.py"), "spec-seed", "--artifact", artifact], capture_output=True, text=True, cwd=str(root))
        ok = proc.returncode == 0
        if ok:
            try: ok = json.loads(proc.stdout).get("verdict") in ("pass","ok")
            except json.JSONDecodeError: ok = False
        if not ok:
            print(json.dumps({"verdict":"warn","action":"freeze-commit","exitCode":proc.returncode,"detail":proc.stdout.strip()})); return 0
        sys.stdout.write(proc.stdout); return 0
    base = args[0] if args else None
    cmd = [sys.executable, str(SCRIPT_DIR/"check_frozen_scan.py")]
    if base: cmd.append(base)
    return subprocess.run(cmd).returncode

if __name__ == "__main__": run_module_main(main)
