#!/usr/bin/env python3
"""Checkbox projection from execution ledger; reject hashed-body writes (PRD 081 R23)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from checkbox_diff import is_checkbox_only_diff, parse_task_checkboxes, toggle_checkbox
from frozen_spec_ledger import (
    effective_task_checkboxes,
    is_frozen_task_list,
    project_checkboxes_from_ledger,
    record_ledger_subtask,
    reject_hashed_body_write,
)
from wave_state import load_deliver_state, task_ledger_tasks


def _usage() -> None:
    print(
        "usage: tasks-progress.py toggle --file PATH --ref TASK_REF [--done true|false] [--phase SLUG]\n"
        "       tasks-progress.py project --file PATH [--state-file PATH]\n"
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
        if token in (
            "--file",
            "--ref",
            "--done",
            "--old",
            "--new",
            "--phase",
            "--state-file",
        ) and i + 1 < len(argv):
            flags[token[2:]] = argv[i + 1]
            i += 2
            continue
        if token in ("-h", "--help"):
            _usage()
            raise SystemExit(0)
        print(json.dumps({"verdict": "fail", "error": "unknown argument"}), file=sys.stderr)
        raise SystemExit(2)
    return cmd, flags


def _load_ledger_tasks(root: Path, state_file: str) -> dict[str, object]:
    if state_file:
        import json as _json

        state = _json.loads(Path(state_file).read_text(encoding="utf-8"))
        return task_ledger_tasks(state)
    try:
        state = load_deliver_state(root)
    except Exception:
        return {}
    return task_ledger_tasks(state)


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    cmd, flags = _parse_flags(args)
    root = Path.cwd()

    if cmd == "toggle":
        file_arg = flags.get("file", "")
        ref = flags.get("ref", "")
        done_arg = flags.get("done", "")
        phase_slug = flags.get("phase", "")
        path = Path(file_arg)
        if not file_arg or not ref or not path.is_file():
            _usage()
            return 2
        old = path.read_text(encoding="utf-8")
        done = None
        if done_arg in ("true", "false"):
            done = done_arg == "true"
        if is_frozen_task_list(old):
            if not phase_slug:
                print(json.dumps({"verdict": "fail", "error": "--phase required for frozen task lists"}))
                return 1
            target_done = done if done is not None else True
            rejected = reject_hashed_body_write(old, old)
            if rejected:
                print(json.dumps(rejected))
                return 1
            ledger_out = record_ledger_subtask(root, ref, phase_slug, done=target_done)
            if ledger_out.get("verdict") not in ("pass", "ok"):
                print(json.dumps(ledger_out))
                return 1
            ledger_tasks = _load_ledger_tasks(root, flags.get("state-file", ""))
            ledger_tasks[ref] = {"done": target_done}
            projected = project_checkboxes_from_ledger(old, ledger_tasks)
            print(
                json.dumps(
                    {
                        "verdict": "pass",
                        "action": "ledger-toggle",
                        "ref": ref,
                        "file": str(path),
                        "projected": projected,
                        "ledger": ledger_out,
                    }
                )
            )
            return 0
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

    if cmd == "project":
        file_arg = flags.get("file", "")
        path = Path(file_arg)
        if not file_arg or not path.is_file():
            _usage()
            return 2
        text = path.read_text(encoding="utf-8")
        ledger_tasks = _load_ledger_tasks(root, flags.get("state-file", ""))
        projected = project_checkboxes_from_ledger(text, ledger_tasks)
        boxes = effective_task_checkboxes(text, ledger_tasks)
        print(
            json.dumps(
                {
                    "verdict": "pass",
                    "action": "project",
                    "file": str(path),
                    "checkboxes": boxes,
                    "text": projected,
                }
            )
        )
        return 0

    if cmd == "check-diff":
        old_path = Path(flags.get("old", ""))
        new_path = Path(flags.get("new", ""))
        if not old_path.is_file() or not new_path.is_file():
            _usage()
            return 2
        old = old_path.read_text(encoding="utf-8")
        new = new_path.read_text(encoding="utf-8")
        rejected = reject_hashed_body_write(old, new)
        if rejected:
            print(json.dumps(rejected))
            return 1
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
        text = path.read_text(encoding="utf-8")
        ledger_tasks = _load_ledger_tasks(root, flags.get("state-file", ""))
        boxes = effective_task_checkboxes(text, ledger_tasks)
        print(json.dumps({"verdict": "pass", "checkboxes": boxes}))
        return 0

    _usage()
    return 2


if __name__ == "__main__":
    run_module_main(main)
