#!/usr/bin/env python3
"""Deterministic in-repo memory search."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import argparse, json, re
    from pathlib import Path
    p = argparse.ArgumentParser()
    p.add_argument("--store", required=True)
    p.add_argument("--query", default="")
    p.add_argument("--category", default="")
    p.add_argument("--tag", default="")
    p.add_argument("--file-glob", default="")
    ns = p.parse_args(list(sys.argv[1:] if argv is None else argv))
    store = Path(ns.store)
    memories = store/"memories"; rules = store/"rules"
    results = []
    def parse_fm(text, field):
        if not text.startswith("---"): return ""
        parts = text.split("---", 2)
        if len(parts) < 3: return ""
        for line in parts[1].splitlines():
            if line.startswith(field+":"):
                return line.split(":",1)[1].strip()
        return ""
    def scan_dir(base: Path):
        if not base.is_dir(): return
        for f in sorted(base.rglob("*.md")):
            if ns.file_glob and not f.match(ns.file_glob): continue
            text = f.read_text(encoding="utf-8", errors="replace")
            cat = parse_fm(text, "category"); tag = parse_fm(text, "tags")
            if ns.category and ns.category not in cat: continue
            if ns.tag and ns.tag not in tag: continue
            if ns.query and ns.query.lower() not in text.lower(): continue
            mid = parse_fm(text, "id") or f.stem
            summary = next((l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("---")), "")
            results.append({"id": mid, "summary": summary[:200]})
    scan_dir(memories); scan_dir(rules)
    print(json.dumps({"results": results}, indent=2)); return 0
    return 0

if __name__ == "__main__":
    run_module_main(main)
