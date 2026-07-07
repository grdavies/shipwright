#!/usr/bin/env python3
"""
# R16 no-regression (PRD 035): frozen immutability, traceability, and spec-rigor gates feed the delivery loop.
R-ID traceability gate."""
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
import spec_union_056
from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="traceability-check.py")
    parser.add_argument("--prd", required=True)
    parser.add_argument("--tasks", required=True)
    parser.add_argument(
        "--no-restate-056",
        action="store_true",
        help="Gate: fail when a union R-ID restates PRD 056 union R1-R20 text (R22).",
    )
    parser.add_argument(
        "--union-056-source",
        default=None,
        help="Local PRD 056 union doc override for the no-restatement gate (fixtures/offline).",
    )
    parser.add_argument(
        "--restate-ratio",
        type=float,
        default=spec_union_056.RESTATEMENT_RATIO,
        help="Similarity threshold (0-1) for the no-restatement gate.",
    )
    args = parser.parse_args(argv)
    root = SCRIPT_DIR.parent
    prd_path = Path(args.prd)
    tasks_path = Path(args.tasks)
    tasks_text = tasks_path.read_text(encoding="utf-8")
    union = json.loads(
        subprocess.check_output([sys.executable, str(root / "scripts/spec-union.py"), str(prd_path)], text=True)
    )
    union_reqs = union.get("requirements", [])
    union_ids = [r["id"] for r in union_reqs]
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
    rc = 0 if verdict == "complete" else 20
    out: dict = {
        "verdict": verdict,
        "unionRids": union_ids,
        "rows": rows,
        "uncovered": sorted(set(uncovered + incomplete)),
    }
    if args.no_restate_056:
        gate = spec_union_056.evaluate(
            union_reqs,
            root,
            source=args.union_056_source,
            ratio=args.restate_ratio,
        )
        out["restatement056"] = gate
        if gate["verdict"] == "restated":
            rc = 20
    print(json.dumps(out, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    run_module_main(main)
