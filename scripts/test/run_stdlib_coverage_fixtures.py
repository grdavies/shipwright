#!/usr/bin/env python3
"""stdlib coverage mode fixtures (PRD 051 TR6/TR7)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR.parent))

from _fixture_lib import repo_root

FAIL = 0


def ok(msg: str) -> None:
    print(f"OK  {msg}")


def bad(msg: str) -> None:
    global FAIL
    print(f"FAIL {msg}")
    FAIL = 1


def main() -> int:
    root = repo_root(__file__)
    runner = root / "scripts/test/_runner.py"
    sample = root / "scripts/test/fixtures/stdlib-coverage-mode-no-behavior-change/sample.test"
    target = root / "scripts/test/fixtures/coverage-target-script.py"

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (str(root / "scripts"), env.get("PYTHONPATH", "")) if p
    )
    ec_plain = subprocess.run(
        [sys.executable, str(runner), "run-test", str(sample)], cwd=str(root), env=env
    ).returncode
    ec_cov = subprocess.run(
        [sys.executable, str(runner), "--coverage", "run-test", str(sample)], cwd=str(root), env=env
    ).returncode
    if ec_plain == ec_cov == 0:
        ok("stdlib-coverage-mode-no-behavior-change: identical exit code")
    else:
        bad(f"stdlib-coverage-mode-no-behavior-change: plain={ec_plain} coverage={ec_cov}")

    with tempfile.TemporaryDirectory() as tmp:
        coverdir = Path(tmp)
        env = os.environ.copy()
        env["SW_COVERAGE"] = "1"
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "trace",
                "--count",
                f"--coverdir={coverdir}",
                str(target),
            ],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            bad(f"trace run failed: {proc.stderr}")
            return FAIL
        report = subprocess.run(
            [
                sys.executable,
                str(root / "scripts/coverage_report.py"),
                "--coverdir",
                str(coverdir),
                "--scripts-root",
                str(root / "scripts"),
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        out = report.stdout
        rel = "test/fixtures/coverage-target-script.py"
        if rel not in out:
            bad("stdlib-coverage-report-executed-and-unexecuted-lines: target missing from report")
            return FAIL
        from coverage_report import aggregate_coverdir

        stats = aggregate_coverdir(coverdir, scripts_root=root / "scripts")
        row = stats.get(rel)
        if row and row["executed"] >= 1 and row["total"] - row["executed"] >= 1:
            ok("stdlib-coverage-report-executed-and-unexecuted-lines: executed and unexecuted lines")
        else:
            bad(f"stdlib-coverage-report-executed-and-unexecuted-lines: stats={row}")

    return FAIL


if __name__ == "__main__":
    raise SystemExit(main())
