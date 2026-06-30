#!/usr/bin/env python3
"""Merge-base sync probe for /sw-stabilize — detect PR merge conflicts before check/thread harvest. """
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, os, re, sys
    text = os.environ.get("MERGE_TREE_OUT", "")
    paths = []
    for line in text.splitlines():
        m = re.match(r"^  base\s+\d+\s+[0-9a-f]+\s+(.+)$", line)
        if m:
            path = m.group(1).strip()
            if path and path not in paths:
                paths.append(path)
    print(json.dumps(paths))
    return 0

if __name__ == "__main__":
    run_module_main(main)
