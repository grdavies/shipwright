"""PRD 081 R10 — freeze ownership and standalone compatibility fixtures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from check_frozen_lib import (
    artifact_is_frozen,
    content_revision,
    freeze_artifact,
    freeze_record_path,
    is_driver_invoked,
    stamp_frozen,
)
import check_frozen_lib
from doc_loop import (
    build_step,
    consume_agent_stage,
    execute_mechanical_stage,
    load_doc_state,
    provision_doc_run,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _write_prd(repo: Path, unit_id: str = "081-prd-workflow") -> str:
    rel = f"docs/prds/{unit_id}/prd.md"
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\ntype: prd\n---\n# PRD\n", encoding="utf-8")
    return rel


def _write_tasks(repo: Path, unit_id: str = "081-prd-workflow") -> str:
    slug = unit_id.split("-prd-", 1)[-1] if "-prd-" in unit_id else unit_id
    rel = f"docs/prds/{unit_id}/tasks-{slug}.md"
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntype: tasks\n---\n# Tasks\n\n### 1. Phase one (R1)\n\n- [ ] 1.1 Do thing\n",
        encoding="utf-8",
    )
    return rel


def _verified_receipt(artifact: str, owner: str) -> dict:
    return {
        "verdict": "pass",
        "artifact": artifact,
        "owner": owner,
        "lifecycleState": "frozen",
        "durabilityState": "verified",
        "revision": "abc123",
        "commitSha": "deadbeef",
        "freezeRecordDigest": "abc123",
        "driverInvoked": True,
    }


def test_orchestrated_freeze_records_owner_once(repo: Path) -> None:
    prd = _write_prd(repo)
    tasks = _write_tasks(repo)
    owner = "doc-loop:doc-test"
    calls: list[str] = []

    def fake_freeze(root, artifact, *, owner, driver_invoked, unit_id=None, freeze_commit_fn=None, issue_store_fn=None):
        calls.append(artifact)
        return _verified_receipt(artifact, owner)

    with patch.object(check_frozen_lib, "freeze_artifact", side_effect=fake_freeze):
        receipt_prd = check_frozen_lib.freeze_artifact(repo, prd, owner=owner, driver_invoked=True)
        receipt_tasks = check_frozen_lib.freeze_artifact(repo, tasks, owner=owner, driver_invoked=True)

    assert receipt_prd["owner"] == owner
    assert receipt_tasks["owner"] == owner
    assert calls == [prd, tasks]
    assert receipt_prd["durabilityState"] == "verified"


def test_direct_operator_warns_on_durability_failure(repo: Path) -> None:
    prd = _write_prd(repo)

    def fail_commit(root, artifact, revision):
        return {"durabilityState": "failed", "detail": {"verdict": "fail"}}

    with patch.object(check_frozen_lib, "verify_file_store_durability", side_effect=fail_commit):
        receipt = check_frozen_lib.freeze_artifact(repo, prd, owner="operator", driver_invoked=False)

    assert receipt["verdict"] == "warn"
    assert receipt["durabilityState"] == "failed"


def test_driver_invoked_fails_on_durability_failure(repo: Path) -> None:
    prd = _write_prd(repo)

    def fail_commit(root, artifact, revision):
        return {"durabilityState": "failed", "detail": {"verdict": "fail"}}

    with patch.object(check_frozen_lib, "verify_file_store_durability", side_effect=fail_commit):
        receipt = check_frozen_lib.freeze_artifact(repo, prd, owner="doc-loop:run", driver_invoked=True)

    assert receipt["verdict"] == "fail"
    assert receipt["error"] == "durability-not-verified"


def test_driver_freeze_stages_record_revisions(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="freeze-topic", tier="Standard")
    run_id = str(provisioned["runId"])
    prd = _write_prd(repo)
    tasks = _write_tasks(repo)
    state = load_doc_state(repo, run_id)
    state["unitIds"] = {"prd": "081-prd-workflow", "tasks": "tasks-081-workflow"}
    state["artifactPaths"] = {"prd": prd, "tasks": tasks}

    with patch(
        "doc_loop.freeze_stage_artifact",
        side_effect=lambda root, st, stage: {
            "verdict": "pass",
            "artifactKey": "prd" if stage == "freeze-prd" else "tasks",
            "receipt": _verified_receipt(prd if stage == "freeze-prd" else tasks, f"doc-loop:{run_id}"),
        },
    ):
        execute_mechanical_stage(repo, state, "freeze-prd")
        state = load_doc_state(repo, run_id)
        execute_mechanical_stage(repo, state, "freeze-tasks")

    state = load_doc_state(repo, run_id)
    assert state["artifactRevisions"]["prd"]["owner"] == f"doc-loop:{run_id}"
    assert state["artifactRevisions"]["tasks"]["durabilityState"] == "verified"


def test_tasks_step_exposes_no_freeze_flag(repo: Path) -> None:
    provisioned = provision_doc_run(repo, topic="tasks-flag", tier="Standard")
    state = load_doc_state(repo, str(provisioned["runId"]))
    consume_agent_stage(repo, state, "triage", outcome={})
    state = load_doc_state(repo, str(provisioned["runId"]))
    for stage in ("prd", "doc-review"):
        consume_agent_stage(repo, state, stage, outcome={})
        state = load_doc_state(repo, str(provisioned["runId"]))
    with patch("doc_loop.freeze_stage_artifact", return_value={"verdict": "pass", "artifactKey": "prd", "receipt": _verified_receipt("", owner="doc-loop:x")}):
        execute_mechanical_stage(repo, state, "freeze-prd")
    state = load_doc_state(repo, str(provisioned["runId"]))
    step = build_step(state, "tasks")
    assert step["noFreeze"] is True


def test_direct_stamp_freeze_still_works(repo: Path) -> None:
    prd = _write_prd(repo)
    path = repo / prd
    assert not artifact_is_frozen(path)
    revision = stamp_frozen(path)
    assert artifact_is_frozen(path)
    assert len(revision) == 64


def test_no_freeze_leaves_tasks_draft(repo: Path) -> None:
    tasks = _write_tasks(repo)
    path = repo / tasks
    assert not artifact_is_frozen(path)
    text = path.read_text(encoding="utf-8")
    assert "frozen: true" not in text


def _git(repo: Path) -> list[str]:
    return ["git", "-c", "user.name=Test", "-c", "user.email=shipwright-ci"]


def _init_git_repo(repo: Path) -> None:
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    git_id = _git(repo)
    subprocess.run([*git_id, "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run([*git_id, "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run([*git_id, "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)


def test_freeze_commit_no_recursive_subprocess(repo: Path) -> None:
    _init_git_repo(repo)
    unit_id = "081-prd-freeze-recursion"
    rel = f"docs/prds/{unit_id}/081-prd-freeze-recursion.md"
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\ntype: prd\ntopic: freeze-recursion\n---\n# PRD\n", encoding="utf-8")
    stamp_frozen(path)
    subprocess.run([*_git(repo), "add", rel], cwd=repo, check=True, capture_output=True)
    subprocess.run([*_git(repo), "commit", "-m", "track prd"], cwd=repo, check=True, capture_output=True)

    real_run = subprocess.run
    nested_freeze_calls = 0

    def counting_run(cmd, *args, **kwargs):
        nonlocal nested_freeze_calls
        argv = cmd if isinstance(cmd, list) else []
        joined = " ".join(str(part) for part in argv)
        if "check-frozen.py" in joined and "freeze-commit" in joined:
            nested_freeze_calls += 1
        if any("freeze_artifact" in str(part) for part in argv):
            nested_freeze_calls += 1
        return real_run(cmd, *args, **kwargs)

    with patch("subprocess.run", side_effect=counting_run):
        proc = real_run(
            [sys.executable, str(scripts / "check-frozen.py"), "freeze-commit", "--artifact", rel],
            cwd=repo,
            capture_output=True,
            text=True,
        )

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert nested_freeze_calls == 0


def test_freeze_owner_conflict(repo: Path) -> None:
    _init_git_repo(repo)
    prd = _write_prd(repo, "081-prd-owner-conflict")
    tasks = _write_tasks(repo, "081-prd-owner-conflict")
    subprocess.run([*_git(repo), "add", prd, tasks], cwd=repo, check=True, capture_output=True)
    subprocess.run([*_git(repo), "commit", "-m", "track prd"], cwd=repo, check=True, capture_output=True)

    def verified_commit(root, artifact, revision):
        return {
            "durabilityState": "verified",
            "commitSha": "deadbeef",
            "freezeRecordDigest": revision,
        }

    first = freeze_artifact(
        repo,
        prd,
        owner="operator",
        driver_invoked=False,
        freeze_commit_fn=verified_commit,
    )
    assert first["verdict"] == "pass"

    second = freeze_artifact(
        repo,
        prd,
        owner="doc-loop:other-run",
        driver_invoked=True,
        freeze_commit_fn=verified_commit,
    )
    assert second["verdict"] == "fail"
    assert second["error"] == "freeze-owner-conflict"


def test_freeze_idempotent_same_owner(repo: Path) -> None:
    _init_git_repo(repo)
    prd = _write_prd(repo, "081-prd-idempotent")
    tasks = _write_tasks(repo, "081-prd-idempotent")
    subprocess.run([*_git(repo), "add", prd, tasks], cwd=repo, check=True, capture_output=True)
    subprocess.run([*_git(repo), "commit", "-m", "track prd"], cwd=repo, check=True, capture_output=True)

    def verified_commit(root, artifact, revision):
        return {
            "durabilityState": "verified",
            "commitSha": "cafebabe",
            "freezeRecordDigest": revision,
        }

    first = freeze_artifact(
        repo,
        prd,
        owner="operator",
        driver_invoked=False,
        freeze_commit_fn=verified_commit,
    )
    assert first["verdict"] == "pass"
    record_path = freeze_record_path(repo, prd)
    assert record_path.is_file()
    before = json.loads(record_path.read_text(encoding="utf-8"))

    second = freeze_artifact(
        repo,
        prd,
        owner="operator",
        driver_invoked=False,
        freeze_commit_fn=verified_commit,
    )
    assert second["verdict"] == "pass"
    assert second.get("note") == "idempotent-freeze-record"
    after = json.loads(record_path.read_text(encoding="utf-8"))
    assert after == before
