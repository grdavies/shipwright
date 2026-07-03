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
    import argparse
    import json
    import re
    from datetime import date

    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list")
    list_p.add_argument("--open-only", action="store_true")
    list_p.add_argument("--backlog", required=True)

    close_p = sub.add_parser("close")
    close_p.add_argument("--signal-id", required=True)
    close_p.add_argument("--backlog", required=True)
    close_p.add_argument("--date", default="")

    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    path = Path(ns.backlog)
    if not path.is_file():
        if ns.cmd == "list":
            print("[]")
            return 0
        print(json.dumps({"error": "backlog not found"}))
        return 2

    text = path.read_text(encoding="utf-8")
    item_re = re.compile(
        r"^-\s+\[([ xX])\]\s+source:feedback\s+pr:#(\d+)\s+signal:([^\s]+)\s+—\s+(.+)$",
        re.M,
    )

    def parse_items():
        items = []
        for m in item_re.finditer(text):
            checked, pr, sig, desc = m.group(1), m.group(2), m.group(3), m.group(4).strip()
            desc_clean = re.sub(r"\s+\(closed:\s*\d{4}-\d{2}-\d{2}\)\s*$", "", desc)
            items.append({
                "open": checked.lower() == " ",
                "prNumber": int(pr),
                "signalId": sig,
                "description": desc_clean,
                "line": m.group(0),
            })
        return items

    if ns.cmd == "list":
        items = parse_items()
        if ns.open_only:
            items = [i for i in items if i["open"]]
        print(json.dumps(items, ensure_ascii=False))
        return 0

    if ns.cmd == "close":
        d = ns.date or date.today().isoformat()
        new_text = text
        found = False
        for m in item_re.finditer(text):
            if m.group(3) != ns.signal_id:
                continue
            if m.group(1).lower() == "x":
                print(json.dumps({"error": "already closed", "signalId": ns.signal_id}))
                return 20
            old = m.group(0)
            desc = re.sub(r"\s+\(closed:.*\)$", "", m.group(4).strip())
            new_line = f"- [x] source:feedback pr:#{m.group(2)} signal:{ns.signal_id} — {desc} (closed: {d})"
            new_text = new_text.replace(old, new_line, 1)
            found = True
            break
        if not found:
            print(json.dumps({"error": "signal not found", "signalId": ns.signal_id}))
            return 20
        path.write_text(new_text, encoding="utf-8")
        print(json.dumps({"closed": True, "signalId": ns.signal_id, "date": d}))
        return 0

    print(json.dumps({"error": f"unknown command: {ns.cmd}"}))
    return 2


if __name__ == "__main__":
    run_module_main(main)
