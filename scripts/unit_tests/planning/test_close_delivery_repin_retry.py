"""PRD 275 R13 — close+re-pin failure is not-ready; retry repairs stale hash."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from planning_canonical import parse_freeze_record_hash
from planning_store import IssueStoreBackend, _default_body_path
from planning_store_facade import _close_issue_store_unit


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _cfg(project_key: str) -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }


def _frozen_tasks(backend: IssueStoreBackend, *, project_key: str, tasks_unit: str) -> str:
    prd_unit = tasks_unit.replace("tasks-", "275-prd-")
    prd_path = _default_body_path(prd_unit, "prd")
    tasks_path = _default_body_path(tasks_unit, "tasks")
    brainstorm_unit = f"brainstorm-{project_key}"
    brainstorm_path = _default_body_path(brainstorm_unit, "brainstorm")

    assert (
        backend.put(
            brainstorm_unit,
            brainstorm_path,
            f"---\nid: {brainstorm_unit}\ntype: brainstorm\nstatus: draft\nvisibility: public\n---\n# B\n",
        ).verdict
        == "ok"
    )
    assert (
        backend.put(
            prd_unit,
            prd_path,
            f"---\nid: {prd_unit}\ntype: prd\nstatus: draft\nvisibility: public\n---\n# P\n",
        ).verdict
        == "ok"
    )
    assert (
        backend.put(
            tasks_unit,
            tasks_path,
            f"---\nid: {tasks_unit}\ntype: tasks\nstatus: draft\nvisibility: public\nprd: {prd_unit}\n---\n# T\n",
        ).verdict
        == "ok"
    )
    for unit, path in (
        (brainstorm_unit, brainstorm_path),
        (prd_unit, prd_path),
        (tasks_unit, tasks_path),
    ):
        assert backend.freeze(unit, path, distill=False)["verdict"] == "ok"
    return tasks_path


def test_close_repin_failure_not_ready_and_retry_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R13 — append failure → fail/not-ready; retry on already-closed repairs hash."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "close-repin-retry-275"
    cfg = _cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    tasks_unit = "tasks-275-close-repin-retry"
    backend = IssueStoreBackend(root, cfg)
    tasks_path = _frozen_tasks(backend, project_key=project_key, tasks_unit=tasks_unit)

    original_comment = backend._client.issue_comment
    calls = {"n": 0}

    def flaky_comment(issue_id: str, body: str, *, markers=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("simulated append timeout")
        return original_comment(issue_id, body, markers=markers)

    monkeypatch.setattr(backend._client, "issue_comment", flaky_comment)

    first = _close_issue_store_unit(
        backend,
        {"unitId": tasks_unit, "artifactType": "tasks", "bodyPath": tasks_path},
        dry_run=False,
    )
    assert first["verdict"] == "fail", first
    assert first.get("error") == "freeze-repin-failed"
    assert first.get("partialApply") is True
    assert first.get("closedOk") is True

    closed = backend._lookup_record(tasks_unit, tasks_path)
    assert closed.state == "closed"
    # Stale pre-close freeze hash still on the issue — get would tamper without repair.
    stale = parse_freeze_record_hash(closed.comments)
    assert stale

    retry = _close_issue_store_unit(
        backend,
        {"unitId": tasks_unit, "artifactType": "tasks", "bodyPath": tasks_path},
        dry_run=False,
    )
    assert retry["verdict"] == "pass", retry
    assert retry.get("alreadyClosed") is True
    assert retry.get("action") == "repin"
    assert retry.get("hash")
    assert retry["hash"] != stale

    got = backend.get(tasks_unit, tasks_path)
    assert got.verdict == "ok"
    assert got.hash == retry["hash"]
