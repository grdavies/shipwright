#!/usr/bin/env python3
"""Parse and mutate prdsDir/GAP-BACKLOG.md (IM8 / U9)."""
from __future__ import annotations
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from _sw.cli import run_module_main

def main(argv: list[str] | None = None) -> int:
    import json, re, sys
    from datetime import date
    from pathlib import Path

    cmd, backlog_path, open_only_s, signal_id, close_date = sys.argv[1:6]
    open_only = open_only_s == "1"
    path = Path(backlog_path)
    text = path.read_text()

    ITEM_RE = re.compile(
        r"^-\s+\[([ xX])\]\s+source:feedback\s+pr:#(\d+)\s+signal:([^\s]+)\s+—\s+(.+)$",
        re.M,
    )

    def parse_items():
        items = []
        for m in ITEM_RE.finditer(text):
            checked, pr, sig, desc = m.group(1), m.group(2), m.group(3), m.group(4).strip()
            open_item = checked.lower() == " "
            desc_clean = re.sub(r"\s+\(closed:\s*\d{4}-\d{2}-\d{2}\)\s*$", "", desc)
            items.append({
                "open": open_item,
                "prNumber": int(pr),
                "signalId": sig,
                "description": desc_clean,
                "line": m.group(0),
            })
        return items

    if cmd == "list":
        items = parse_items()
        if open_only:
            items = [i for i in items if i["open"]]
        print(json.dumps(items, ensure_ascii=False))
        sys.exit(0)

    if cmd == "close":
        if not signal_id:
            print(json.dumps({"error": "signal-id required"}))
            sys.exit(2)
        d = close_date or date.today().isoformat()
        new_text = text
        found = False
        for m in ITEM_RE.finditer(text):
            if m.group(3) != signal_id:
                continue
            if m.group(1).lower() == "x":
                print(json.dumps({"error": "already closed", "signalId": signal_id}))
                sys.exit(20)
            old = m.group(0)
            desc = re.sub(r"\s+\(closed:.*\)$", "", m.group(4).strip())
            new_line = f"- [x] source:feedback pr:#{m.group(2)} signal:{signal_id} — {desc} (closed: {d})"
            new_text = new_text.replace(old, new_line, 1)
            found = True
            break
        if not found:
            print(json.dumps({"error": "signal not found", "signalId": signal_id}))
            sys.exit(20)
        path.write_text(new_text)
        print(json.dumps({"closed": True, "signalId": signal_id, "date": d}))
        sys.exit(0)

    print(json.dumps({"error": f"unknown command: {cmd}"}))
    sys.exit(2)
    return 0

if __name__ == "__main__":
    run_module_main(main)
