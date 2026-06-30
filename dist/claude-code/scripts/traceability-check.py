#!/usr/bin/env python3
"""R-ID traceability gate."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="traceability-check.py")
    parser.add_argument("--prd", required=True)
    parser.add_argument("--tasks", required=True)
    args = parser.parse_args(argv)
    root = SCRIPT_DIR.parent
    prd_path = Path(args.prd)
    tasks_path = Path(args.tasks)
    tasks_text = tasks_path.read_text(encoding="utf-8")
    union = json.loads(
        subprocess.check_output([sys.executable, str(root / "scripts/spec-union.py"), str(prd_path)], text=True)
    )
    union_ids = [r["id"] for r in union.get("requirements", [])]
    rows = doc_format.extract_traceability_rows(tasks_text)
    covered = {
        r["rid"]: r
        for r in rows
        if r["testScenario"] and r["testScenario"].lower() not in ("tbd", "todo", "n/a")
    }
    uncovered = [
        rid
        for rid in union_ids
        if rid not in covered or not covered[rid]["testScenario"].strip()
    ]
    incomplete = [
        r["rid"]
        for r in rows
        if r["rid"] in union_ids
        and (not r["testScenario"] or r["testScenario"].lower() in ("tbd", "todo", "n/a"))
    ]
    verdict = "complete" if not uncovered and not incomplete else "gaps"
    print(
        json.dumps(
            {
                "verdict": verdict,
                "unionRids": union_ids,
                "rows": rows,
                "uncovered": sorted(set(uncovered + incomplete)),
            },
            ensure_ascii=False,
        )
    )
    return 0 if verdict == "complete" else 20


if __name__ == "__main__":
    run_module_main(main)
