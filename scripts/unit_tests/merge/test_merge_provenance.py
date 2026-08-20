"""Unit tests for merge provenance resolver (PRD 323 phase 2)."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from pathlib import Path

from execute_task_status import status_path

import merge_provenance as mp

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "merge-provenance"
GOLDEN = FIXTURES / "golden.json"

TASKS_FIXTURE = """---
unit-id: tasks-fixture-provenance
prd: docs/prds/323-fixture/323-prd-fixture.md
topic: fixture-provenance
frozen: true
---

# Tasks fixture

### 2. Provenance infrastructure — medium

- [ ] 2.1 Define provenance record schema and resolver API (R10, R15)
  - **File:** `scripts/merge_provenance.py`
  - **Expected:** resolves hunk paths to PRD unit, task ref, phase slug, commit rationale
- [ ] 2.2 Index task ledger and execute receipts for provenance lookup (R10)
  - **File:** `scripts/merge_provenance.py`
  - **Expected:** issue-store virtual paths supported via unit-id handles
- [ ] 2.3 Unit tests for provenance resolver fixtures (R10, R15)
  - **File:** `scripts/unit_tests/merge/test_merge_provenance.py`
  - **Expected:** golden conflict files map to expected intent records
"""

PRD_FIXTURE = """---
unit-id: 323-prd-fixture-provenance
topic: fixture-provenance
---

# PRD fixture
"""


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
    tasks_path = root / "docs/prds/323-fixture/tasks-fixture-provenance.md"
    prd_path = root / "docs/prds/323-fixture/323-prd-fixture.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(TASKS_FIXTURE, encoding="utf-8")
    prd_path.write_text(PRD_FIXTURE, encoding="utf-8")
    (root / "scripts/merge_provenance.py").parent.mkdir(parents=True, exist_ok=True)
    (root / "scripts/merge_provenance.py").write_text("# fixture\n", encoding="utf-8")
    (root / "scripts/unit_tests/merge/test_merge_provenance.py").parent.mkdir(parents=True, exist_ok=True)
    (root / "scripts/unit_tests/merge/test_merge_provenance.py").write_text("# fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)


def _write_execute_receipts(root: Path, receipts: dict[str, dict]) -> None:
    for ref, payload in receipts.items():
        path = status_path(root, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"taskRef": ref, **payload}
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def test_build_index_maps_task_files(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    index = mp.build_index(tmp_path, task_list)
    bindings = index.by_path.get("scripts/merge_provenance.py")
    assert bindings is not None
    refs = {binding.task_ref for binding in bindings}
    assert refs == {"2.1", "2.2"}
    primary = mp.select_binding(bindings, execute_receipts=index.execute_receipts)
    assert primary is not None
    assert primary.task_ref == "2.1"
    assert primary.phase_id == "2"
    assert primary.phase_slug == "provenance-infrastructure-medium"
    assert index.prd_unit_id == "323-prd-fixture-provenance"
    assert index.tasks_unit_id == "tasks-fixture-provenance"


def test_virtual_path_binding_for_issue_store_logical_path(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    index = mp.build_index(tmp_path, task_list)
    logical = "scripts/merge_provenance.py"
    virtual = mp._virtual_body_path(logical)
    assert virtual.startswith(".cursor/planning-materialized/")
    assert virtual in index.by_path
    assert index.by_path[virtual][0].task_ref == "2.1"


def test_execute_receipts_indexed(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    _write_execute_receipts(
        tmp_path,
        {
            "2.2": {
                "verdict": "green",
                "rationale": "index execute receipts for lookup",
            }
        },
    )
    index = mp.build_index(tmp_path, task_list)
    assert "2.2" in index.execute_receipts
    assert index.execute_receipts["2.2"]["rationale"] == "index execute receipts for lookup"


def test_ledger_overlay_marks_done(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    deliver_state = {
        "taskLedger": {
            "tasks": {
                "2.1": {"done": True, "phase": "provenance-infrastructure-medium"},
            }
        }
    }
    index = mp.build_index(tmp_path, task_list, deliver_state=deliver_state)
    bindings = index.by_path["scripts/merge_provenance.py"]
    binding = next(item for item in bindings if item.task_ref == "2.1")
    assert binding.done is True
    assert binding.phase_slug == "provenance-infrastructure-medium"


def test_resolve_paths_left_right(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    _write_execute_receipts(
        tmp_path,
        {
            "2.1": {
                "verdict": "green",
                "rationale": "left-side provenance",
            }
        },
    )
    result = mp.resolve_paths(
        tmp_path,
        ["scripts/merge_provenance.py"],
        left_head=None,
        right_head=None,
        task_list=task_list,
    )
    left = result["records"]["left"][0]
    right = result["records"]["right"][0]
    assert left["side"] == "LEFT"
    assert right["side"] == "RIGHT"
    assert left["taskRef"] == "2.1"
    assert left["rationale"] == "left-side provenance"
    assert left["executeReceipt"]["verdict"] == "green"


def test_golden_conflict_fixtures(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    for case in golden["cases"]:
        execute_base = tmp_path / ".cursor" / "sw-execute-runs"
        if execute_base.is_dir():
            shutil.rmtree(execute_base)
        _write_execute_receipts(tmp_path, case.get("executeReceipts") or {})
        result = mp.resolve_paths(
            tmp_path,
            [case["path"]],
            left_head=case.get("leftHead"),
            right_head=case.get("rightHead"),
            task_list=task_list,
        )
        left = result["records"]["left"][0]
        expected = dict(case["expectedLeft"])
        expected.setdefault("prdUnitId", "323-prd-fixture-provenance")
        expected.setdefault("unitId", "tasks-fixture-provenance")
        for key, value in expected.items():
            assert left.get(key) == value, f"{case['path']}:{key}"
        if "expectedRight" in case:
            right = result["records"]["right"][0]
            for key, value in case["expectedRight"].items():
                assert right.get(key) == value, f"{case['path']}:right:{key}"


def test_cli_resolve_batch(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    out = tmp_path / "resolved.json"
    with pytest.raises(SystemExit) as exc:
        mp.main(
            [
                "--root",
                str(tmp_path),
                "resolve-batch",
                "--paths",
                "scripts/merge_provenance.py,scripts/unit_tests/merge/test_merge_provenance.py",
                "--tasks",
                task_list,
                "--out",
                str(out),
            ]
        )
    assert exc.value.code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["verdict"] == "pass"
    assert len(payload["records"]["left"]) == 2
