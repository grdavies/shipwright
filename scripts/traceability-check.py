#!/usr/bin/env python3
"""R-ID → task → test traceability gate (pre-task-freeze). Usage: traceability-check.py --prd PRD --tasks TASKS"""
from __future__ import annotations

import sys

from _sw.cli import run_module_main


def main(argv: list[str] | None = None) -> int:
    import json, subprocess, sys
    from pathlib import Path

    sys.path.insert(0, str(Path(sys.argv[1]) / "scripts"))
    import doc_format

    root, prd_path, tasks_path = sys.argv[1:4]
    tasks_text = Path(tasks_path).read_text()

    union = json.loads(
        subprocess.check_output(["bash", str(Path(root) / "scripts/spec-union.py"), prd_path], text=True)
    )
    union_ids = [r["id"] for r in union.get("requirements", [])]

    rows = doc_format.extract_traceability_rows(tasks_text)

    covered = {r["rid"]: r for r in rows if r["testScenario"] and r["testScenario"].lower() not in ("tbd", "todo", "n/a")}
    uncovered = [rid for rid in union_ids if rid not in covered or not covered[rid]["testScenario"].strip()]
    incomplete = [r["rid"] for r in rows if r["rid"] in union_ids and (not r["testScenario"] or r["testScenario"].lower() in ("tbd", "todo", "n/a"))]

    verdict = "complete" if not uncovered and not incomplete else "gaps"
    out = {
        "verdict": verdict,
        "unionRids": union_ids,
        "rows": rows,
        "uncovered": sorted(set(uncovered + incomplete)),
    }
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(0 if verdict == "complete" else 20)
    return 0


if __name__ == "__main__":
    run_module_main(main)
