#!/usr/bin/env python3
"""PRD 039 R11 — require non-empty ZOMBIES checklist when testScenario is set."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from _sw.cli import run_module_main

PLACEHOLDER = frozenset({"", "tbd", "todo", "n/a", "none"})


def has_scenario(value: str) -> bool:
    return value.strip().lower() not in PLACEHOLDER


def checklist_nonempty(value) -> bool:
    if value is None:
        return False
    if isinstance(value, list):
        return any(str(x).strip() for x in value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return any(str(x).strip() for x in parsed)
            except json.JSONDecodeError:
                pass
        return True
    return False


def parse_tasks_zombies(tasks_text: str, task_ref: str) -> tuple[str, str]:
    """Best-effort parse of optional 4th column ZOMBIES checklist in traceability table."""
    scenario = ""
    zombies = ""
    mode = False
    for line in tasks_text.splitlines():
        if re.match(r"^##\s+Traceability\s*$", line, re.I):
            mode = True
            continue
        if mode and line.startswith("## "):
            mode = False
        if not mode:
            continue
        parts = [p.strip() for p in line.strip().strip("|").split("|")]
        if len(parts) < 3:
            continue
        rid, task, scen = parts[0], parts[1], parts[2]
        if rid.lower() == "r-id":
            continue
        if task != task_ref:
            continue
        scenario = scen
        if len(parts) >= 4:
            zombies = parts[3]
    return scenario, zombies


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="zombies_gate")
    parser.add_argument("--record", help="JSON record with testScenario + zombiesChecklist")
    parser.add_argument("--tasks", help="Task list markdown path")
    parser.add_argument("--task-ref", help="Task ref when using --tasks")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    scenario = ""
    checklist = None

    if args.record:
        try:
            data = json.loads(Path(args.record).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(json.dumps({"verdict": "fail", "error": "invalid record"}))
            return 20
        scenario = str(data.get("testScenario") or "")
        checklist = data.get("zombiesChecklist")
    elif args.tasks and args.task_ref:
        text = Path(args.tasks).read_text(encoding="utf-8")
        scenario, ztxt = parse_tasks_zombies(text, args.task_ref)
        checklist = ztxt
    else:
        print(json.dumps({"verdict": "fail", "error": "missing --record or --tasks + --task-ref"}))
        return 20

    if not has_scenario(scenario):
        print(json.dumps({"verdict": "pass", "reason": "no bound testScenario"}))
        return 0

    if not checklist_nonempty(checklist):
        print(
            json.dumps(
                {
                    "verdict": "fail",
                    "reason": "zombiesChecklist required when testScenario is set",
                    "testScenario": scenario,
                }
            )
        )
        return 20

    print(
        json.dumps(
            {
                "verdict": "pass",
                "testScenario": scenario,
                "zombiesChecklist": checklist,
            }
        )
    )
    return 0


if __name__ == "__main__":
    run_module_main(main)
