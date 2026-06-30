#!/usr/bin/env python3
"""Assert README + docs/guides cover PRD 009 surfaces."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, re
    root = SCRIPT_DIR.parent
    fail = 0
    docs = [root/"README.md", root/"docs/guides/getting-started.md", root/"docs/guides/workflows.md",
            root/"docs/guides/configuration.md", root/"docs/guides/commands.md"]
    patterns = [
        ("deliver.autonomy", r"deliver\.autonomy"),
        ("legitimate.halt", r"(legitimate\.halt|Legitimate\.halt|legitimate halt)"),
        ("living-doc", r"(living\.doc|INDEX\.md|COMPLETION-LOG|GAP-BACKLOG)"),
        ("frontmatter", r"(brainstorm:|prd:|frontmatter)"),
    ]
    for f in docs:
        label = f.name
        if not f.is_file():
            print(f"FAIL {label}: missing file {f}"); fail = 1; continue
        text = f.read_text(encoding="utf-8", errors="replace")
        for pname, pat in patterns:
            if re.search(pat, text): print(f"OK  {pname} in {label}")
            else: print(f"FAIL {pname}: pattern not found in {f}"); fail = 1
    legacy = 0
    for f in docs:
        if f.is_file() and re.search(r"/pf-|pf-", f.read_text(encoding="utf-8", errors="replace")):
            print(f"FAIL legacy pf- ref in {f}"); legacy = 1; fail = 1
    if legacy == 0: print("OK  user-docs-no-legacy-refs")
    if fail:
        print(json.dumps({"verdict":"fail","action":"docs-presence-check"})); return 1
    print(json.dumps({"verdict":"pass","action":"docs-presence-check"})); return 0
    return 0

if __name__ == "__main__":
    run_module_main(main)
