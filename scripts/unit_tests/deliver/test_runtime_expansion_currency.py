"""Frozen runtime children require native integration evidence, durable across teardown."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
TASKS = """---
frozen: true
---
### 1. Alpha

- [ ] 1.1 Parent
  - **File:** `child.txt`
### 2. Beta

- [ ] 2.1 Other parent
  - **File:** `other.txt`
"""


def run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=root, text=True, capture_output=True, timeout=30)


def git(root: Path, *args: str) -> str:
    proc = run(root, "git", *args)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def native(tmp_path: Path) -> dict:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.email", "fixture@example.com")
    git(tmp_path, "config", "user.name", "Fixture")
    git(tmp_path, "checkout", "-q", "-b", "phase-alpha")
    task_file = tmp_path / "tasks.md"
    task_file.write_text(TASKS)
    git(tmp_path, "add", "tasks.md")
    git(tmp_path, "commit", "-q", "-m", "frozen parent")
    git(tmp_path, "checkout", "-q", "-b", "child-alpha")
    (tmp_path / "child.txt").write_text("implemented\n")
    git(tmp_path, "add", "child.txt")
    git(tmp_path, "commit", "-q", "-m", "child implementation")
    git(tmp_path, "checkout", "-q", "phase-alpha")
    receipts = tmp_path / "receipts"
    plan = {"version": 1, "tier": "execute", "phaseId": "1", "phaseSlug": "alpha",
            "refs": [{"id": "1.1.1", "parentRef": "1.1", "synthetic": True,
                      "branch": "child-alpha", "status": "pending"}]}
    write(receipts / "execute-step-plan.json", plan)
    proc = run(tmp_path, sys.executable, str(SCRIPTS / "execute_integrate.py"), str(tmp_path),
               "integrate", "--task-ref", "1.1.1", "--phase-slug", "alpha",
               "--run-dir", str(receipts), "--source-ref", "child-alpha")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    state_file = tmp_path / ".cursor" / "sw-deliver-state.json"
    state = {"runId": "fixture-run", "source_task_list": "tasks.md",
             "phases": {"1": {"id": "1", "slug": "alpha", "branch": "phase-alpha", "status": "in-flight"}},
             "taskLedger": {"tasks": {"1.1": {"done": True, "phase": "alpha"}}, "phases": {}}}
    write(state_file, state)
    return {"root": tmp_path, "receipts": receipts, "state": state_file, "tasks": task_file}


def ledger(native: dict, *args: str) -> subprocess.CompletedProcess[str]:
    return run(native["root"], sys.executable, str(SCRIPTS / "wave_state.py"),
               str(native["root"]), "ledger", *args)


def record(native: dict, *, proof: bool = True) -> subprocess.CompletedProcess[str]:
    args = ["record", "--task", "1.1.1", "--phase", "alpha", "--done", "true"]
    if proof:
        args += ["--execute-run-dir", str(native["receipts"])]
    return ledger(native, *args)


def check(native: dict) -> subprocess.CompletedProcess[str]:
    return ledger(native, "check", "--tasks-file", "tasks.md")


def test_native_child_currency_survives_receipt_teardown(native: dict) -> None:
    before = native["tasks"].read_bytes()
    proc = record(native)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    state = json.loads(native["state"].read_text())
    assert state["taskLedger"]["tasks"]["1.1.1"].get("runtimeCompletion"), state
    shutil.rmtree(native["receipts"])
    proc = check(native)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert native["tasks"].read_bytes() == before


def test_done_alone_does_not_prove_runtime_child(native: dict) -> None:
    assert record(native, proof=False).returncode == 0
    assert check(native).returncode == 1


@pytest.mark.parametrize("fault", ["synthetic", "parent", "cross-phase-parent", "phase", "withdrawn",
                                  "journal-source", "journal-commit", "latest-failure", "duplicate", "unrelated-commit"])
def test_invalid_native_evidence_rejected_without_state_write(native: dict, fault: str) -> None:
    plan_path = native["receipts"] / "execute-step-plan.json"
    journal_path = native["receipts"] / "integrate-journal.json"
    plan = json.loads(plan_path.read_text())
    journal = json.loads(journal_path.read_text())
    ref = plan["refs"][0]
    if fault == "synthetic":
        ref["synthetic"] = False
    elif fault == "parent":
        ref["parentRef"] = "1.9"
    elif fault == "cross-phase-parent":
        ref["parentRef"] = "2.1"
    elif fault == "phase":
        plan["phaseSlug"] = "beta"
    elif fault == "withdrawn":
        ref["status"] = "withdrawn"
    elif fault == "journal-source":
        journal["entries"][-1]["sourceRef"] = "wrong-child"
    elif fault == "journal-commit":
        journal["entries"][-1]["mergeCommit"] = "a" * 40
    elif fault == "latest-failure":
        journal["entries"].append({"taskRef": "1.1.1", "verdict": "fail"})
    elif fault == "duplicate":
        plan["refs"].append(dict(ref))
    elif fault == "unrelated-commit":
        git(native["root"], "checkout", "-q", "--orphan", "unrelated")
        git(native["root"], "commit", "-q", "--allow-empty", "-m", "unrelated")
        unrelated = git(native["root"], "rev-parse", "HEAD")
        git(native["root"], "checkout", "-q", "phase-alpha")
        ref["mergeCommit"] = unrelated
        journal["entries"][-1]["mergeCommit"] = unrelated
    write(plan_path, plan)
    write(journal_path, journal)
    before = native["state"].read_bytes()
    proc = record(native)
    assert proc.returncode != 0, proc.stdout
    assert "runtime" in proc.stdout.lower(), proc.stdout
    assert native["state"].read_bytes() == before


@pytest.mark.parametrize("fault", ["body", "phase-owner", "run", "reopened", "unknown", "nonfrozen", "removed-proof"])
def test_durable_proof_never_waives_stale_or_unknown_entries(native: dict, fault: str) -> None:
    assert record(native).returncode == 0
    state = json.loads(native["state"].read_text())
    if fault == "body":
        native["tasks"].write_text(TASKS.replace("Parent", "Changed parent"))
    elif fault == "phase-owner":
        state["taskLedger"]["tasks"]["1.1.1"]["phase"] = "beta"
    elif fault == "run":
        state["runId"] = "different-run"
    elif fault == "reopened":
        state["phases"]["1"]["branch"] = "missing-phase-branch"
    elif fault == "unknown":
        state["taskLedger"]["tasks"]["1.9.1"] = {"done": True, "phase": "alpha"}
    elif fault == "nonfrozen":
        native["tasks"].write_text(TASKS.replace("frozen: true", "frozen: false"))
    elif fault == "removed-proof":
        state["taskLedger"]["tasks"]["1.1.1"].pop("runtimeCompletion", None)
    write(native["state"], state)
    assert check(native).returncode == 1


def test_teardown_uses_phase_merge_commit_after_branch_deletion(native: dict) -> None:
    assert record(native).returncode == 0
    head = git(native["root"], "rev-parse", "HEAD")
    git(native["root"], "checkout", "-q", "-b", "integration-target")
    git(native["root"], "branch", "-D", "phase-alpha")
    state = json.loads(native["state"].read_text())
    state["phases"]["1"].update(status="teardown-complete", mergeCommit=head)
    write(native["state"], state)
    shutil.rmtree(native["receipts"])
    proc = check(native)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_native_plan_preserves_synthetic_expansion_provenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import execute_plan
    import phase_sizing

    monkeypatch.setattr(phase_sizing, "score_execute_ref", lambda *_args: {
        "overThreshold": True, "separableSets": [["a.py"], ["b.py"]],
    })
    expanded, _, _ = execute_plan.runtime_expand_refs(
        tmp_path, TASKS, "1", [{"id": "1.1", "title": "Parent", "files": ["a.py", "b.py"]}], {},
    )
    refs = execute_plan.build_execute_refs("feature", "alpha", expanded)
    assert [ref["id"] for ref in refs] == ["1.1.1", "1.1.2"]
    assert all(ref.get("parentRef") == "1.1" and ref.get("synthetic") is True for ref in refs)
