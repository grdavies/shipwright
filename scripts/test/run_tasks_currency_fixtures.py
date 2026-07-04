#!/usr/bin/env python3
"""Tasks currency phase-scoped fixtures (PRD 055 R12)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main
from _sw.vendor_paths import repo_root


def main(argv: list[str] | None = None) -> int:
    root = repo_root(__file__)
    state_py = root / "scripts" / "wave_state.py"

    with tempfile.TemporaryDirectory() as tmp:
        fix = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=fix, check=True)
        subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=fix, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=fix, check=True)
        tasks_rel = "docs/prds/099-test/tasks-099-test.md"
        (fix / "docs/prds/099-test").mkdir(parents=True, exist_ok=True)
        (fix / tasks_rel).write_text(
            """---
frozen: true
---
### 3. Phase three

- [ ] 3.1 Open task
  - **File:** `a.py`
- [ ] 3.2 Another open
  - **File:** `b.py`
""",
            encoding="utf-8",
        )
        subprocess.run(["git", "add", "."], cwd=fix, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=fix, check=True)
        (fix / ".cursor").mkdir(exist_ok=True)
        (fix / ".cursor/sw-deliver-state.json").write_text(
            json.dumps(
                {
                    "verdict": "running",
                    "source_task_list": tasks_rel,
                    "taskLedger": {"tasks": {}, "phases": {}},
                }
            ),
            encoding="utf-8",
        )

        proc = subprocess.run(
            [
                sys.executable,
                str(state_py),
                str(fix),
                "ledger",
                "check",
                "--tasks-file",
                tasks_rel,
                "--phase-id",
                "3",
                "--merge-ready",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode == 1 and "tasks-currency-unchecked-completed-work" in (proc.stdout + proc.stderr):
            print("OK  tasks-currency-unchecked-completed-work")
            return 0
        print("FAIL tasks-currency-unchecked-completed-work")
        print(proc.stdout)
        print(proc.stderr)
        return 1


if __name__ == "__main__":
    run_module_main(main)
