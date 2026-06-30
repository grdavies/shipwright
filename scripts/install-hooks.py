#!/usr/bin/env python3
"""Bootstrap git hooks for Shipwright doc-freeze local warning."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import os, subprocess
    from sw_resolve_plugin_root import resolve_plugin_root
    p = subprocess.run(["git","rev-parse","--show-toplevel"], capture_output=True, text=True)
    root = Path(p.stdout.strip()) if p.returncode==0 else SCRIPT_DIR.parent
    plugin_root = resolve_plugin_root(SCRIPT_DIR)
    hooks = plugin_root/"hooks"
    try: hooks_rel = os.path.relpath(str(hooks), str(root))
    except ValueError: hooks_rel = str(hooks)
    for rel in ("scripts/check-frozen.py","hooks/pre-commit-frozen.py","hooks/pre-commit"):
        target = plugin_root.parent/rel if rel.startswith("scripts") else hooks/Path(rel).name
        if target.is_file(): target.chmod(0o755)
    subprocess.run(["git","config","core.hooksPath", hooks_rel], cwd=str(root), check=True)
    print(f"Installed hooks: core.hooksPath={hooks_rel}")
    print("Local freeze hook is early-warning only; CI check-frozen.py is authoritative.")
    return 0
    return 0

if __name__ == "__main__":
    run_module_main(main)
