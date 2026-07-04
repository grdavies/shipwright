#!/usr/bin/env python3
"""Tasks authoring execute-tier granularity fixtures (PRD 055 R19)."""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format
from _sw.cli import run_module_main
from _sw.vendor_paths import repo_root


def ok(name: str) -> None:
    print(f"OK  {name}")


def bad(name: str, detail: str = "") -> None:
    print(f"FAIL {name}")
    if detail:
        print(detail)


def extract_granularity_json(text: str) -> dict | None:
    match = re.search(r"^## Execute-tier granularity\s*$([\s\S]*?)(?=^##\s|\Z)", text, re.MULTILINE)
    if not match:
        return None
    block = match.group(1)
    fence = re.search(r"```json\s*([\s\S]*?)```", block)
    if not fence:
        return None
    return json.loads(fence.group(1))


def scenario_sw_tasks_execute_granularity(root: Path) -> bool:
    gen_py = root / "scripts" / "tasks_generate.py"
    suite_paths = [
        "scripts/test/fixtures/suite-a/harness.py",
        "scripts/test/fixtures/suite-b/harness.py",
        "scripts/test/fixtures/suite-c/harness.py",
        "scripts/test/fixtures/suite-d/harness.py",
    ]
    file_field = ", ".join(f"`{path}`" for path in suite_paths)
    n = len(suite_paths)

    with tempfile.TemporaryDirectory() as tmp:
        fix = Path(tmp)
        tasks_rel = "docs/prds/099-granularity/tasks-099-granularity.md"
        (fix / "docs/prds/099-granularity").mkdir(parents=True)
        (fix / ".cursor").mkdir(exist_ok=True)
        (fix / ".cursor/workflow.config.json").write_text(
            json.dumps(
                {
                    "execute": {
                        "enabled": True,
                        "sizing": {
                            "thresholds": {
                                "filesTouched": 3,
                                "distinctDirs": 2,
                                "traceabilityScenarios": 2,
                            }
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        task_body = f"""---
frozen: false
topic: execute-granularity-fixture
---

## Relevant Files

- `{suite_paths[0]}`

## Tasks

### 1. Port test suites (medium)

- [ ] 1.1 Port N suites to pytest harness
  - **File:** {file_field}
  - **Expected:** each suite registered in suite-registry.json
  - **R-IDs:** R16

## Phase Dependencies

| Phase | Depends on |
|-------|------------|
| 1 | none |

## Traceability

| R-ID | Task | Scenario | ZOMBIES |
|------|------|----------|---------|
| R16 | 1.1 | sw-tasks-execute-granularity | Z |
"""
        task_path = fix / tasks_rel
        task_path.write_text(task_body, encoding="utf-8")

        proc = subprocess.run(
            [
                sys.executable,
                str(gen_py),
                "--root",
                str(fix),
                "apply-granularity",
                "--task-list",
                tasks_rel,
                "--inplace",
            ],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            bad("sw-tasks-execute-granularity", proc.stdout + proc.stderr)
            return False

        text = task_path.read_text(encoding="utf-8")
        refs = doc_format.extract_executable_subtasks(text, "1")
        payload = extract_granularity_json(text)
        serial_edges = []
        if payload:
            for split in payload.get("refSplits", []):
                serial_edges.extend(split.get("serialEdges") or [])

        if len(refs) >= n:
            ok("sw-tasks-execute-granularity")
            return True
        if serial_edges:
            ok("sw-tasks-execute-granularity")
            return True

        bad(
            "sw-tasks-execute-granularity",
            f"expected >={n} refs or serial edges; got {len(refs)} refs, {len(serial_edges)} serial edges",
        )
        return False


def main(argv: list[str] | None = None) -> int:
    root = repo_root(__file__)
    return 0 if scenario_sw_tasks_execute_granularity(root) else 1


if __name__ == "__main__":
    run_module_main(main)
