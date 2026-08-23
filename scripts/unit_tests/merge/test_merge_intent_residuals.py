"""Residual hardening tests for merge provenance + intent resolve (PRD 326 phase 3 / gap 320)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import merge_intent_resolve as mir
import merge_provenance as mp

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "merge-provenance"
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
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)


def test_unattributed_path_emits_explicit_intent(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    result = mp.resolve_paths(
        tmp_path,
        ["docs/prds/323-fixture/323-prd-fixture.md"],
        left_head=None,
        right_head=None,
        task_list=task_list,
    )
    left = result["records"]["left"][0]
    assert left["resolved"] is False
    assert left["intent"] == mp.UNATTRIBUTED_INTENT


def test_resolve_paths_canonical_byte_identical(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    paths = [
        "scripts/unit_tests/merge/test_merge_provenance.py",
        "scripts/merge_provenance.py",
        "docs/prds/323-fixture/323-prd-fixture.md",
    ]
    first = mp.resolve_paths(
        tmp_path,
        paths,
        left_head=None,
        right_head=None,
        task_list=task_list,
    )
    second = mp.resolve_paths(
        tmp_path,
        list(reversed(paths)),
        left_head=None,
        right_head=None,
        task_list=task_list,
    )
    assert mp.canonical_json_dumps(first) == mp.canonical_json_dumps(second)


def test_ambiguous_intent_halts_on_conflicting_task_refs(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    rel = "scripts/merge_provenance.py"
    rel_path = tmp_path / rel
    rel_path.write_text("left-version\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "feat(provenance): define resolver schema and index API"],
        cwd=tmp_path,
        check=True,
    )
    left_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    rel_path.write_text("right-version\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "index execute receipts for lookup"],
        cwd=tmp_path,
        check=True,
    )
    right_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    batch = mp.resolve_paths(
        tmp_path,
        [rel],
        left_head=left_head,
        right_head=right_head,
        task_list=task_list,
    )
    left_records = list(batch["records"]["left"])
    right_records = list(batch["records"]["right"])
    assert left_records[0]["taskRef"] == "2.1"
    assert right_records[0]["taskRef"] == "2.2"
    payload = mir.halt_ambiguous_intent_payload(
        conflict_paths=[rel],
        left_records=left_records,
        right_records=right_records,
    )
    assert payload["verdict"] == "halt"
    assert payload["reason"] == "ambiguous-intent"
    assert rel in payload["paths"]
    task_refs = {item["taskRef"] for item in payload["intents"]}
    assert task_refs == {"2.1", "2.2"}


def test_ambiguous_intent_cli_exit_20(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-provenance.md"
    rel = "scripts/merge_provenance.py"
    rel_path = tmp_path / rel
    rel_path.write_text("left-version\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "feat(provenance): define resolver schema and index API"],
        cwd=tmp_path,
        check=True,
    )
    left_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    rel_path.write_text("right-version\n", encoding="utf-8")
    subprocess.run(["git", "add", rel], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "index execute receipts for lookup"],
        cwd=tmp_path,
        check=True,
    )
    right_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    proc = subprocess.run(
        [
            "python3",
            str(Path(__file__).resolve().parents[2] / "merge_intent_resolve.py"),
            "--root",
            str(tmp_path),
            "classify",
            "--paths",
            rel,
            "--tasks",
            task_list,
            "--phase-slug",
            "provenance-infrastructure-medium",
            "--left-head",
            left_head,
            "--right-head",
            right_head,
        ],
        text=True,
        capture_output=True,
    )
    assert proc.returncode == mir.AMBIGUOUS_INTENT_EXIT, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "halt"
    assert payload["reason"] == "ambiguous-intent"
    assert {item["taskRef"] for item in payload["intents"]} == {"2.1", "2.2"}


def test_mirror_parity_merge_scripts() -> None:
    root = Path(__file__).resolve().parents[3]
    for name in ("merge_provenance.py", "merge_intent_resolve.py"):
        scripts_path = root / "scripts" / name
        core_path = root / "core" / "scripts" / name
        assert scripts_path.read_bytes() == core_path.read_bytes(), name
