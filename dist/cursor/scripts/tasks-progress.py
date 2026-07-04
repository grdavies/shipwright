#!/usr/bin/env python3
"""Toggle task checkboxes on frozen task files; reject non-checkbox edits (R13/R14)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from checkbox_diff import is_checkbox_only_diff, parse_task_checkboxes, toggle_checkbox


def _usage() -> None:
    print(
        "usage: tasks-progress.py toggle --file PATH --ref TASK_REF [--done true|false]\n"
        "       tasks-progress.py check-diff --old PATH --new PATH\n"
        "       tasks-progress.py parse --file PATH",
        file=sys.stderr,
    )


def _parse_flags(argv: list[str]) -> tuple[str, dict[str, str]]:
    if not argv:
        _usage()
        raise SystemExit(2)
    cmd = argv[0]
    flags: dict[str, str] = {}
    i = 1
    while i < len(argv):
        token = argv[i]
        if token in ("--file", "--ref", "--done", "--old", "--new") and i + 1 < len(argv):
            flags[token[2:]] = argv[i + 1]
            i += 2
            continue
        if token in ("-h", "--help"):
            _usage()
            raise SystemExit(0)
        print(json.dumps({"verdict": "fail", "error": "unknown argument"}), file=sys.stderr)
        raise SystemExit(2)
    return cmd, flags


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    cmd, flags = _parse_flags(args)

    if cmd == "toggle":
        file_arg = flags.get("file", "")
        ref = flags.get("ref", "")
        done_arg = flags.get("done", "")
        path = Path(file_arg)
        if not file_arg or not ref or not path.is_file():
            _usage()
            return 2
        old = path.read_text(encoding="utf-8")
        done = None
        if done_arg in ("true", "false"):
            done = done_arg == "true"
        try:
            new = toggle_checkbox(old, ref, done)
        except ValueError as exc:
            print(json.dumps({"verdict": "fail", "error": str(exc)}))
            return 1
        if not is_checkbox_only_diff(old, new):
            print(json.dumps({"verdict": "fail", "error": "non-checkbox edit rejected"}))
            return 1
        path.write_text(new, encoding="utf-8")
        print(json.dumps({"verdict": "pass", "action": "toggle", "ref": ref, "file": str(path)}))
        return 0

    if cmd == "check-diff":
        old_path = Path(flags.get("old", ""))
        new_path = Path(flags.get("new", ""))
        if not old_path.is_file() or not new_path.is_file():
            _usage()
            return 2
        old = old_path.read_text(encoding="utf-8")
        new = new_path.read_text(encoding="utf-8")
        if is_checkbox_only_diff(old, new):
            print(json.dumps({"verdict": "pass", "checkboxOnly": True}))
            return 0
        print(json.dumps({"verdict": "fail", "checkboxOnly": False}))
        return 1

    if cmd == "parse":
        path = Path(flags.get("file", ""))
        if not path.is_file():
            _usage()
            return 2
        boxes = parse_task_checkboxes(path.read_text(encoding="utf-8"))
        print(json.dumps({"verdict": "pass", "checkboxes": boxes}))
        return 0

    _usage()
    return 2


if __name__ == "__main__":
    run_module_main(main)
