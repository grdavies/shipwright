#!/usr/bin/env python3
"""Fixture gate for PRD 040 phase sizing scorer (Phase 2)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAIL = 0


def ok(name: str) -> None:
    print(f"OK  {name}")


def bad(name: str) -> None:
    global FAIL
    print(f"FAIL {name}")
    FAIL = 1


def run_score(task_list: str) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts/phase_sizing.py"), "--root", str(ROOT), "score", task_list],
        env={**dict(**{"PYTHONPATH": str(ROOT / "scripts")})},
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout)


def main() -> int:
    task_list = "docs/prds/040-phase-granularity-parallelism/tasks-040-phase-granularity-parallelism.md"
    first = run_score(task_list)
    second = run_score(task_list)
    if json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True):
        ok("phase-sizing-determinism")
    else:
        bad("phase-sizing-determinism")
    phase2 = next(p for p in first["phases"] if p["phase"] == "2")
    if phase2["size"] in {"small", "medium", "large"} and isinstance(phase2["separableSets"], list):
        ok("phase-sizing-classification-shape")
    else:
        bad("phase-sizing-classification-shape")
    if "scopeUnderDeclared" in phase2:
        ok("phase-sizing-scope-under-declared")
    else:
        bad("phase-sizing-scope-under-declared")
    frozen = subprocess.run(
        [sys.executable, str(ROOT / "scripts/phase_sizing.py"), "--root", str(ROOT), "check-frozen", task_list],
        env={"PYTHONPATH": str(ROOT / "scripts")},
        text=True,
        capture_output=True,
    )
    if frozen.returncode == 20:
        ok("phase-sizing-check-frozen-failclosed")
    else:
        bad("phase-sizing-check-frozen-failclosed")
    if (ROOT / "core/sw-reference/phase-sizing.schema.json").is_file():
        ok("phase-sizing-schema-present")
    else:
        bad("phase-sizing-schema-present")
    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
