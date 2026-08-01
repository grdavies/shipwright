"""PRD 085 R14 — doc-to-feature handoff lock and real feature-seed publication fixtures."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import wave_spec_seed as wss
from doc_loop import publication_mode, run_feature_seed
from wave_lock import doc_to_feature_handoff_lock_path_for, target_lock_path_for
from wave_spec_seed_guard import acquire_doc_to_feature_handoff_lock
from wave_target_lock import acquire_target_lock

_REAL_SUBPROCESS_RUN = subprocess.run


def _run_spec_seed_inprocess(cmd: list[str], **kwargs):
    if "spec-seed" not in cmd:
        return _REAL_SUBPROCESS_RUN(cmd, **kwargs)
    root = Path(cmd[cmd.index("spec-seed") - 1]).resolve()
    args = cmd[cmd.index("spec-seed") + 1 :]
    docs_dir = root / "docs/prds/085-demo"
    target_branch = "feat/085-demo"
    buf = io.StringIO()
    rc = 0
    old_cwd = os.getcwd()
    os.chdir(root)
    original_resolve = wss.resolve_target_branch
    wss.resolve_target_branch = lambda _root, _rel: (target_branch, "085-demo", docs_dir)
    try:
        with patch(
            "planning_artifact_handle.issue_store_separate_project_effective",
            return_value=False,
        ), redirect_stdout(buf):
            try:
                wss.cmd_spec_seed(root, args)
            except SystemExit as exc:
                code = exc.code
                rc = int(code) if isinstance(code, int) else (0 if code is None else 1)
    finally:
        wss.resolve_target_branch = original_resolve
        os.chdir(old_cwd)
    return subprocess.CompletedProcess(cmd, rc, buf.getvalue(), "")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    (root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "branch", "-M", "main"], cwd=root, check=True, capture_output=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _verified_receipt(artifact: str) -> dict:
    return {
        "verdict": "pass",
        "artifact": artifact,
        "owner": "doc-loop:test",
        "lifecycleState": "frozen",
        "durabilityState": "verified",
        "revision": "abc123",
    }


def _feature_seed_state(repo: Path, run_id: str = "doc-r14-a") -> dict:
    (repo / "docs/brainstorms").mkdir(parents=True, exist_ok=True)
    brainstorm = repo / "docs/brainstorms/085-demo-brainstorm.md"
    brainstorm.write_text(
        "---\ntype: brainstorm\nvisibility: public\n---\n# Brainstorm\n",
        encoding="utf-8",
    )
    docs_dir = repo / "docs/prds/085-demo"
    docs_dir.mkdir(parents=True)
    prd = docs_dir / "085-prd-demo.md"
    prd.write_text(
        "---\n"
        "type: prd\n"
        "frozen: true\n"
        "visibility: public\n"
        "brainstorm: docs/brainstorms/085-demo-brainstorm.md\n"
        "---\n"
        "# PRD\n",
        encoding="utf-8",
    )
    tasks = docs_dir / "tasks-085-demo.md"
    tasks.write_text(
        "---\ntype: tasks\nfrozen: true\nvisibility: public\nprd: 085-prd-demo\n---\n# Tasks\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "docs"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add docs"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return {
        "runId": run_id,
        "topic": "085-demo",
        "unitIds": {"prd": "085-prd-demo", "tasks": "tasks-085-demo"},
        "artifactPaths": {
            "prd": "docs/prds/085-demo/085-prd-demo.md",
            "tasks": "docs/prds/085-demo/tasks-085-demo.md",
        },
        "artifactRevisions": {
            "prd": _verified_receipt("docs/prds/085-demo/085-prd-demo.md"),
            "tasks": _verified_receipt("docs/prds/085-demo/tasks-085-demo.md"),
        },
        "pendingRelatedWork": {"status": "acknowledged"},
    }


def test_feature_seed_real_commit_releases_handoff_lock(repo: Path) -> None:
    state = _feature_seed_state(repo)
    run_id = f"doc-loop:{state['runId']}"
    target_branch = "feat/085-demo"

    with patch(
        "planning_artifact_handle.issue_store_separate_project_effective",
        return_value=False,
    ), patch(
        "wave_spec_seed.resolve_target_branch",
        return_value=(target_branch, "085-demo", repo / "docs/prds/085-demo"),
    ), patch("subprocess.run", side_effect=_run_spec_seed_inprocess):
        outcome = run_feature_seed(repo, state)

    assert outcome["verdict"] == "pass"
    receipt = outcome["receipt"]
    assert receipt["remoteState"]["dryRun"] is False
    commit_sha = receipt["remoteState"].get("commit") or outcome["seed"].get("commit")
    if commit_sha:
        show = subprocess.run(
            ["git", "rev-parse", target_branch],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        )
        assert show.stdout.strip() == commit_sha
    else:
        assert outcome["seed"].get("skipped") is True
        assert (
            subprocess.run(
                ["git", "show-ref", "--verify", f"refs/heads/{target_branch}"],
                cwd=repo,
                capture_output=True,
            ).returncode
            == 0
        )
    lock_path = doc_to_feature_handoff_lock_path_for(repo, target_branch, run_id)
    assert not lock_path.is_file()


def test_separate_project_store_only_skip_unchanged(repo: Path) -> None:
    state = _feature_seed_state(repo)
    with patch("planning_artifact_handle.issue_store_separate_project_effective", return_value=True):
        assert publication_mode(repo) == "separate-project-store-only"
        outcome = run_feature_seed(repo, state)
    assert outcome["skipped"] is True
    assert outcome["reason"] == "separate-project-store-only"


def test_feature_seed_target_lock_conflict_fails_closed(repo: Path) -> None:
    state = _feature_seed_state(repo, run_id="doc-r14-c")
    target_branch = "feat/085-demo"
    held = acquire_target_lock(repo, target_branch, "deliver-other-run")
    assert held["verdict"] == "pass"

    with patch(
        "planning_artifact_handle.issue_store_separate_project_effective",
        return_value=False,
    ), patch(
        "wave_spec_seed.resolve_target_branch",
        return_value=(target_branch, "085-demo", repo / "docs/prds/085-demo"),
    ), patch(
        "doc_link.check_artifact",
        return_value={"verdict": "pass"},
    ):
        outcome = run_feature_seed(repo, state)

    assert outcome["verdict"] == "fail"
    assert outcome["halt"] == "target-lock-conflict"
    lock_path = target_lock_path_for(repo, target_branch)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    assert meta["runId"] == "deliver-other-run"
    handoff_path = doc_to_feature_handoff_lock_path_for(
        repo, target_branch, f"doc-loop:{state['runId']}"
    )
    assert not handoff_path.is_file()


def test_handoff_lock_acquire_refuses_live_target_lock(repo: Path) -> None:
    target_branch = "feat/conflict"
    acquire_target_lock(repo, target_branch, "deliver-holder")
    out = acquire_doc_to_feature_handoff_lock(repo, target_branch, "doc-loop:probe")
    assert out["verdict"] == "fail"
    assert out["error"] == "target-lock-conflict"
