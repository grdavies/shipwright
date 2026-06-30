#!/usr/bin/env python3
"""Toggle task checkboxes on frozen task files; reject non-checkbox edits (R13/R14). """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json
    import subprocess
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(sys.argv[4]).parent))
    from checkbox_diff import is_checkbox_only_diff, toggle_checkbox

    path = Path(sys.argv[1])
    ref = sys.argv[2]
    done_arg = sys.argv[3]
    old = path.read_text(encoding="utf-8")
    done = None
    if done_arg in ("true", "false"):
        done = done_arg == "true"
    try:
        new = toggle_checkbox(old, ref, done)
    except ValueError as exc:
        print(json.dumps({"verdict": "fail", "error": str(exc)}))
        sys.exit(1)
    if not is_checkbox_only_diff(old, new):
        print(json.dumps({"verdict": "fail", "error": "non-checkbox edit rejected"}))
        sys.exit(1)
    path.write_text(new, encoding="utf-8")
    print(json.dumps({"verdict": "pass", "action": "toggle", "ref": ref, "file": str(path)}))
    return 0

if __name__ == "__main__":
    run_module_main(main)
