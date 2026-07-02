#!/usr/bin/env python3
"""PRD 049 TR4 — gap_backlog flip --schedule --force fixtures."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS_ROOT = SCRIPT_DIR.parents[1]
_TEST_DIR = _SCRIPTS_ROOT / "test"
for _entry in (str(_TEST_DIR), str(_SCRIPTS_ROOT)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from _fixture_lib import repo_root


def main() -> int:
    root = repo_root(__file__)
    gap_py = root / "scripts" / "gap_backlog.py"
    fail = 0

    def ok(name: str) -> None:
        print(f"OK  {name}")

    def bad(name: str) -> None:
        nonlocal fail
        print(f"FAIL {name}")
        fail = 1

    with tempfile.TemporaryDirectory() as td:
        repo = Path(td) / "repo"
        repo.mkdir()
        gap_path = repo / "docs" / "prds" / "GAP-BACKLOG.md"
        gap_path.parent.mkdir(parents=True)
        gap_path.write_text(
            """# GAP-BACKLOG

| resolved | 0 |
| scheduled | 1 |
| open | 0 |

| ID | Status | Schedule | Title |
|--------|--------|----------|-------|
| GAP-099 | scheduled | PRD 033 A3 | fixture gap |
| GAP-100 | scheduled | PRD 048 | unrelated |
""",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "scripts")

        proc = subprocess.run(
            [sys.executable, str(gap_py), "--root", str(repo), "flip", "--schedule", "--gaps", "GAP-099", "--prd", "049", "--force"],
            capture_output=True,
            text=True,
            env=env,
        )
        if proc.returncode != 0:
            bad("gap-backlog-flip-schedule-force-reschedule")
        else:
            body = gap_path.read_text()
            if "GAP-099 | scheduled | PRD 049" in body:
                ok("gap-backlog-flip-schedule-force-reschedule")
            else:
                bad("gap-backlog-flip-schedule-force-reschedule")

        proc2 = subprocess.run(
            [sys.executable, str(gap_py), "--root", str(repo), "flip", "--schedule", "--gaps", "GAP-100", "--prd", "049"],
            capture_output=True,
            text=True,
            env=env,
        )
        body2 = gap_path.read_text()
        if "GAP-100 | scheduled | PRD 048" in body2:
            ok("gap-backlog-flip-schedule-no-force-noop")
        else:
            bad("gap-backlog-flip-schedule-no-force-noop")

    return fail


if __name__ == "__main__":
    raise SystemExit(main())
