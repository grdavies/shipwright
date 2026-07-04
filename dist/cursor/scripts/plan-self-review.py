#!/usr/bin/env python3
"""Executable-plan self-review for task sub-items (IM6 / U7)."""
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

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--task-ref", default="")
    ns = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    tasks_file = ns.tasks
    task_ref = ns.task_ref
    path = Path(tasks_file)
    if not path.is_file():
        print(json.dumps({"verdict": "fail", "error": "tasks file not found"}))
        return 20

    text = path.read_text(encoding="utf-8")
    findings = []
    placeholder = re.compile(r"\b(TBD|TODO|FIXME|\.\.\.|placeholder)\b", re.I)

    def add(severity: str, message: str, ref: str | None = None) -> None:
        f: dict = {"severity": severity, "message": message}
        if ref:
            f["taskRef"] = ref
        findings.append(f)

    def extract_blocks():
        lines = text.splitlines()
        blocks = []
        current_ref = None
        current_lines: list[str] = []
        item_re = re.compile(r"^\s*-\s+\[[ xX]\]\s+(\d+(?:\.\d+)?)\b")
        for line in lines:
            m = item_re.match(line)
            if m:
                ref = m.group(1)
                if current_ref and current_lines:
                    blocks.append((current_ref, current_lines))
                current_ref = ref
                current_lines = [line]
            elif current_ref is not None:
                if item_re.match(line) and not line.startswith("    "):
                    blocks.append((current_ref, current_lines))
                    current_ref = item_re.match(line).group(1)
                    current_lines = [line]
                else:
                    current_lines.append(line)
        if current_ref and current_lines:
            blocks.append((current_ref, current_lines))
        return blocks

    blocks = extract_blocks()
    if task_ref:
        blocks = [(r, ls) for r, ls in blocks if r == task_ref or r.startswith(task_ref + ".")]

    if not blocks:
        add("error", "no checklist items found" + (f" for ref {task_ref}" if task_ref else ""))
        print(json.dumps({"verdict": "fail", "findings": findings}))
        return 20

    for ref, lines in blocks:
        if "." not in ref:
            continue
        body = "\n".join(lines)
        has_file = bool(re.search(r"\*\*File(s)?:\*\*", body, re.I)) or "`" in body
        has_expected = bool(re.search(r"\*\*Expected:\*\*", body, re.I))
        if not has_file:
            add("error", "missing **File:** or path for executable sub-task", ref)
        if not has_expected:
            add("error", "missing **Expected:** for executable sub-task", ref)
        if placeholder.search(body):
            add("error", "placeholder marker in executable sub-task", ref)
        em = re.search(r"\*\*Expected:\*\*\s*(.+)", body, re.I)
        if em and len(em.group(1).strip()) < 8:
            add("warn", "Expected text very short", ref)

    worst = "pass"
    if any(f["severity"] == "error" for f in findings):
        worst = "fail"
    elif any(f["severity"] == "warn" for f in findings):
        worst = "warn"

    out = {"verdict": worst, "findings": findings, "taskRef": task_ref or None}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if worst == "pass" else 10 if worst == "warn" else 20


if __name__ == "__main__":
    run_module_main(main)
