"""Unit and integration tests for intent-aware merge resolution (PRD 323 phase 3)."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import merge_intent_resolve as mir
import merge_provenance as mp
from execute_task_status import status_path

FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "merge-intent"
GOLDEN = FIXTURES / "golden.json"

TASKS_FIXTURE = """---
unit-id: tasks-fixture-intent
prd: docs/prds/323-fixture/323-prd-fixture-intent.md
topic: fixture-intent
frozen: true
---

# Tasks fixture

### 3. Intent-aware merge resolution — large

- [ ] 3.1 Implement intent comparator and proposal builder (R11, R12)
  - **File:** `scripts/shared.py`
  - **Expected:** classifies deterministic-regen, compatible-merge, semantic-ambiguous
- [ ] 3.2 Integrate intent merge into merge-queue conflict path (R13, R14, R15)
  - **File:** `scripts/a.py`
  - **Expected:** invokes intent resolver after deterministic auto-regen fails
- [ ] 3.3 Human halt payload for semantic-ambiguous conflicts (R13, R21)
  - **File:** `scripts/b.py`
  - **Expected:** typed halt with resumeCommand and proposal artifact path
"""

PRD_FIXTURE = """---
unit-id: 323-prd-fixture-intent
topic: fixture-intent
---

# PRD fixture
"""


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "fixture"], cwd=root, check=True)
    tasks_path = root / "docs/prds/323-fixture/tasks-fixture-intent.md"
    prd_path = root / "docs/prds/323-fixture/323-prd-fixture-intent.md"
    tasks_path.parent.mkdir(parents=True, exist_ok=True)
    tasks_path.write_text(TASKS_FIXTURE, encoding="utf-8")
    prd_path.write_text(PRD_FIXTURE, encoding="utf-8")
    for rel in (
        "scripts/shared.py",
        "scripts/a.py",
        "scripts/b.py",
        "scripts/merge_intent_resolve.py",
    ):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture {rel}\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=root, check=True)


def _write_execute_receipts(root: Path, receipts: dict[str, dict]) -> None:
    for ref, payload in receipts.items():
        path = status_path(root, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"taskRef": ref, **payload}
        path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


def _records_for_case(
    root: Path,
    case: dict,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None, str | None]:
    task_list = "docs/prds/323-fixture/tasks-fixture-intent.md"
    path = str(case["path"])
    left_receipt = case.get("leftReceipt") or {}
    right_receipt = case.get("rightReceipt") or {}
    receipts: dict[str, dict] = {}
    if left_receipt.get("taskRef"):
        receipts[str(left_receipt["taskRef"])] = left_receipt
    if right_receipt.get("taskRef") and right_receipt.get("taskRef") not in receipts:
        receipts[str(right_receipt["taskRef"])] = right_receipt
    _write_execute_receipts(root, receipts)

    left_head = None
    right_head = None
    rel = root / path
    if case.get("leftCommitMessage"):
        rel.parent.mkdir(parents=True, exist_ok=True)
        rel.write_text("left-version\n", encoding="utf-8")
        subprocess.run(["git", "add", path], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", case["leftCommitMessage"]], cwd=root, check=True)
        left_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if case.get("rightCommitMessage"):
        rel.write_text("right-version\n", encoding="utf-8")
        subprocess.run(["git", "add", path], cwd=root, check=True)
        subprocess.run(["git", "commit", "-q", "-m", case["rightCommitMessage"]], cwd=root, check=True)
        right_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()

    batch = mp.resolve_paths(
        root,
        [path],
        left_head=left_head,
        right_head=right_head,
        task_list=task_list,
    )
    return list(batch["records"]["left"]), list(batch["records"]["right"]), left_head, right_head


def test_intent_classification_golden(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    cases = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    for case in cases:
        left_records, right_records, _, _ = _records_for_case(tmp_path, case)
        intent_class, decisions = mir.classify_conflict_from_records(
            tmp_path,
            conflict_paths=[case["path"]],
            left_records=left_records,
            right_records=right_records,
            merging_phase_slug="intent-aware-merge-resolution-large",
        )
        assert intent_class == case["expectedClass"], case
        if case.get("expectedSide"):
            assert decisions[0]["chosenSide"] == case["expectedSide"], case


def test_proposal_artifact_shape(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    task_list = "docs/prds/323-fixture/tasks-fixture-intent.md"
    _write_execute_receipts(
        tmp_path,
        {
            "3.1": {"verdict": "green", "rationale": "shared intent"},
        },
    )
    batch = mp.resolve_paths(
        tmp_path,
        ["scripts/shared.py"],
        left_head=None,
        right_head=None,
        task_list=task_list,
    )
    intent_class, path_decisions = mir.classify_conflict_from_records(
        tmp_path,
        conflict_paths=["scripts/shared.py"],
        left_records=list(batch["records"]["left"]),
        right_records=list(batch["records"]["right"]),
        merging_phase_slug="intent-aware-merge-resolution-large",
    )
    proposal = mir.build_proposal(
        tmp_path,
        conflict_paths=["scripts/shared.py"],
        left_records=list(batch["records"]["left"]),
        right_records=list(batch["records"]["right"]),
        path_decisions=path_decisions,
        intent_class=intent_class,
        phase_slug="intent-aware-merge-resolution-large",
        phase_branch="feat/demo-phase-3",
        target="feat/demo",
        task_list=task_list,
    )
    assert proposal["intentClass"] == "compatible-merge"
    assert proposal["chosenSide"] in {"LEFT", "RIGHT"}
    assert isinstance(proposal["verificationCommands"], list) and proposal["verificationCommands"]
    assert proposal["mergedIntentSummary"]
    assert proposal["records"]["left"] and proposal["records"]["right"]
    assert proposal["pathDecisions"][0]["intentClass"] == "compatible-merge"


def test_semantic_halt_payload_includes_resume_command(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    state = {
        "source_task_list": "docs/prds/323-fixture/tasks-fixture-intent.md",
        "target": {"branch": "feat/demo"},
    }
    proposal_path = mir.write_proposal(
        tmp_path,
        "intent-aware-merge-resolution-large",
        {
            "verdict": "pass",
            "intentClass": "semantic-ambiguous",
            "conflictPaths": ["scripts/a.py"],
        },
    )
    result = {
        "proposalPath": str(proposal_path),
        "proposal": {"intentClass": "semantic-ambiguous"},
        "conflictPaths": ["scripts/a.py"],
    }
    halt = mir.semantic_halt_payload(
        result,
        tmp_path,
        state,
        phase_slug="intent-aware-merge-resolution-large",
        phase_branch="feat/demo-phase-3",
        target="feat/demo",
        orchestrator_worktree=tmp_path,
    )
    assert halt["intentClass"] == "semantic-ambiguous"
    assert halt["proposalPath"] == str(proposal_path)
    assert "resumeCommand" in halt
    assert "merge exec" in halt["resumeCommand"]


def test_deterministic_golden_path_preserved_without_intent_merge(tmp_path: Path) -> None:
    merge_py = Path(__file__).resolve().parents[2] / "wave_merge.py"
    fix = tmp_path / "regen"
    fix.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fix, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=fix, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=fix, check=True)
    (fix / "shared.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "shared.txt"], cwd=fix, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=fix, check=True)
    subprocess.run(["git", "branch", "-m", "feat/target"], cwd=fix, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feat/target-phase-a"], cwd=fix, check=True)
    parity = fix / "scripts/test/fixtures/parity"
    parity.mkdir(parents=True, exist_ok=True)
    (parity / "cursor-golden.manifest").write_text("golden-a\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=fix, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "a"], cwd=fix, check=True)
    subprocess.run(["git", "checkout", "-q", "feat/target"], cwd=fix, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feat/target-phase-b"], cwd=fix, check=True)
    parity.mkdir(parents=True, exist_ok=True)
    (parity / "cursor-golden.manifest").write_text("golden-b\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=fix, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "b"], cwd=fix, check=True)
    subprocess.run(["git", "checkout", "-q", "feat/target"], cwd=fix, check=True)
    state_doc = {
        "target": {"branch": "feat/target"},
        "phases": {"1": {"slug": "a", "branch": "feat/target-phase-a"}},
        "mergeQueue": [{"phaseSlug": "a", "head": "phase-a"}],
        "orchestratorWorktree": {"path": str(fix)},
    }
    (fix / ".cursor").mkdir(exist_ok=True)
    (fix / ".cursor/sw-deliver-state.json").write_text(json.dumps(state_doc) + "\n", encoding="utf-8")
    env = {**os.environ, "SW_DETERMINISTIC_REGEN_STUB": "pass", "SW_INTENT_MERGE_ENABLED": "0"}
    proc = subprocess.run(
        [
            "python3",
            str(merge_py),
            str(fix),
            "merge",
            "exec",
            "--phase-slug",
            "a",
            "--phase-branch",
            "feat/target-phase-a",
            "--target",
            "feat/target",
            "--orchestrator-worktree",
            str(fix),
        ],
        cwd=str(fix),
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("verdict") == "pass"


def test_semantic_conflict_halts_when_intent_merge_enabled(tmp_path: Path) -> None:
    merge_py = Path(__file__).resolve().parents[2] / "wave_merge.py"
    fix = tmp_path / "semantic"
    fix.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=fix, check=True)
    subprocess.run(["git", "config", "user.email", "fixture@test"], cwd=fix, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=fix, check=True)
    (fix / "src.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.txt"], cwd=fix, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=fix, check=True)
    subprocess.run(["git", "branch", "-m", "feat/target"], cwd=fix, check=True)
    subprocess.run(["git", "checkout", "-q", "-b", "feat/target-phase-a"], cwd=fix, check=True)
    (fix / "src.txt").write_text("phase-a\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.txt"], cwd=fix, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "a"], cwd=fix, check=True)
    subprocess.run(["git", "checkout", "-q", "feat/target"], cwd=fix, check=True)
    (fix / "src.txt").write_text("target-tip\n", encoding="utf-8")
    subprocess.run(["git", "add", "src.txt"], cwd=fix, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "target-tip"], cwd=fix, check=True)
    tasks = fix / "docs/prds/323-fixture/tasks-fixture-intent.md"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    tasks.write_text(TASKS_FIXTURE, encoding="utf-8")
    (fix / "docs/prds/323-fixture/323-prd-fixture-intent.md").write_text(PRD_FIXTURE, encoding="utf-8")
    state_doc = {
        "target": {"branch": "feat/target"},
        "phases": {"3": {"slug": "a", "branch": "feat/target-phase-a"}},
        "mergeQueue": [{"phaseSlug": "a", "head": "phase-a"}],
        "orchestratorWorktree": {"path": str(fix)},
        "source_task_list": "docs/prds/323-fixture/tasks-fixture-intent.md",
    }
    (fix / ".cursor").mkdir(exist_ok=True)
    (fix / ".cursor/sw-deliver-state.json").write_text(json.dumps(state_doc) + "\n", encoding="utf-8")
    env = {**os.environ, "SW_DETERMINISTIC_REGEN_STUB": "pass", "SW_INTENT_MERGE_ENABLED": "1"}
    proc = subprocess.run(
        [
            "python3",
            str(merge_py),
            str(fix),
            "merge",
            "exec",
            "--phase-slug",
            "a",
            "--phase-branch",
            "feat/target-phase-a",
            "--target",
            "feat/target",
            "--orchestrator-worktree",
            str(fix),
        ],
        cwd=str(fix),
        env=env,
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 20, proc.stdout + proc.stderr
    payload = json.loads(proc.stdout)
    assert payload.get("cause") == "merge-queue:semantic-ambiguous"
    assert payload.get("intentClass") == "semantic-ambiguous"
    assert payload.get("proposalPath")
    assert payload.get("resumeCommand")
