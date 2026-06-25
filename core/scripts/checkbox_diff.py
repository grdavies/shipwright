#!/usr/bin/env python3
"""Shared checkbox-only diff predicate for frozen task files (R48/R14)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

CHECKBOX_LINE = re.compile(r"^(\s*-\s+)\[([ xX])\](.*)$")


def is_checkbox_only_diff(old_text: str, new_text: str) -> bool:
    """True when the only changes are [ ] <-> [x] on markdown task checkbox lines."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    if len(old_lines) != len(new_lines):
        return False
    for old_line, new_line in zip(old_lines, new_lines):
        if old_line == new_line:
            continue
        old_cb = CHECKBOX_LINE.match(old_line)
        new_cb = CHECKBOX_LINE.match(new_line)
        if not old_cb or not new_cb:
            return False
        if old_cb.group(1) != new_cb.group(1) or old_cb.group(3) != new_cb.group(3):
            return False
        if old_cb.group(2).lower() == new_cb.group(2).lower():
            return False
    return True


def parse_task_checkboxes(text: str) -> dict[str, bool]:
    """Map task ref ids (e.g. '7.1') to done state from markdown task lines."""
    out: dict[str, bool] = {}
    current_ref: str | None = None
    for line in text.splitlines():
        ref_match = re.match(r"^-\s+\[([ xX])\]\s+(\d+\.\d+)\s", line)
        if ref_match:
            done = ref_match.group(1).lower() == "x"
            current_ref = ref_match.group(2)
            out[current_ref] = done
            continue
        sub_ref = re.match(r"^\s+-\s+\*\*File:\*\*", line)
        if sub_ref and current_ref:
            continue
    return out


def toggle_checkbox(text: str, task_ref: str, done: bool | None = None) -> str:
    """Toggle or set checkbox for task ref (e.g. '7.1'). Raises ValueError on invalid edit."""
    pattern = re.compile(
        rf"^(-\s+)\[([ xX])\](\s+{re.escape(task_ref)}\s)",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"task ref not found: {task_ref}")
    old_mark = match.group(2)
    new_mark = "x" if (done if done is not None else old_mark.lower() != "x") else " "
    new_text = (
        text[: match.start(2)]
        + new_mark
        + text[match.end(2) :]
    )
    if not is_checkbox_only_diff(text, new_text):
        raise ValueError("edit would change more than checkbox state")
    return new_text


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "usage: checkbox_diff.py is-checkbox-only <old-file> <new-file>",
            file=sys.stderr,
        )
        sys.exit(2)
    cmd = sys.argv[1]
    if cmd == "is-checkbox-only":
        if len(sys.argv) != 4:
            print("usage: checkbox_diff.py is-checkbox-only <old> <new>", file=sys.stderr)
            sys.exit(2)
        old = Path(sys.argv[2]).read_text(encoding="utf-8")
        new = Path(sys.argv[3]).read_text(encoding="utf-8")
        print("yes" if is_checkbox_only_diff(old, new) else "no")
        sys.exit(0 if is_checkbox_only_diff(old, new) else 1)
    print(f"unknown command: {cmd}", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
