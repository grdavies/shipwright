"""Unit tests for tasks_generate wiring-field gate (PRD 085 R15)."""
from __future__ import annotations

from pathlib import Path

import tasks_generate as tg


MINIMAL_TASK_LIST = """---
type: tasks
status: proposed
---

## Tasks

### 1. Wiring proof fixture (R15)

- [ ] 1.1 Add CLI subcommand (R15)
  - **File:** `scripts/example_cli.py`
  - **Expected:** adds a new CLI subcommand
"""


def test_expected_matches_wiring_category_cli_subcommand():
    assert tg.expected_matches_wiring_category("adds a new CLI subcommand") == "cli-subcommand"


def test_check_wiring_fields_rejects_missing_wired(tmp_path: Path):
    task_list = tmp_path / "tasks.md"
    task_list.write_text(MINIMAL_TASK_LIST, encoding="utf-8")
    result = tg.check_granularity(tmp_path, task_list)
    assert result["verdict"] == "fail"
    assert any("missing Wired" in f for f in result["failures"])


def test_check_wiring_fields_passes_with_wired(tmp_path: Path):
    task_list = tmp_path / "tasks.md"
    task_list.write_text(
        MINIMAL_TASK_LIST.replace(
            "  - **Expected:** adds a new CLI subcommand",
            "  - **Expected:** adds a new CLI subcommand\n"
            "  - **Wired:** `scripts/cli_dispatch.py`",
        ),
        encoding="utf-8",
    )
    result = tg.check_granularity(tmp_path, task_list)
    wiring_failures = [f for f in result["failures"] if "missing Wired" in f]
    assert not wiring_failures
