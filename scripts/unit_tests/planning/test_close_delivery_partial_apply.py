"""PRD 275 R14 — partial-apply (close ok, append fail) + fault injection."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import IssueRevisionConflict
from planning_canonical import parse_freeze_record_hash
from planning_store import IssueStoreBackend, _close_issue_store_unit, _default_body_path


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


@pytest.mark.parametrize(
    "fault",
    [
        "timeout",
        "conflict",
    ],
)
def test_partial_apply_append_timeout_conflict_faults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """R14 — detect close-ok/append-fail; fault inject timeout/conflict; verify final hash."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = f"close-partial-{fault}-275"
    cfg = _cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    tasks_unit = f"tasks-275-partial-{fault}"
    backend = IssueStoreBackend(root, cfg)
    tasks_path = _frozen_tasks(backend, project_key=project_key, tasks_unit=tasks_unit)

    original_comment = backend._client.issue_comment
    fail_once = {"done": False}

    def faulting_comment(issue_id: str, body: str, *, markers=None):
        if not fail_once["done"]:
            fail_once["done"] = True
            if fault == "timeout":
                raise TimeoutError("simulated append timeout")
            raise IssueRevisionConflict(expected="etag-a", actual="etag-b")
        return original_comment(issue_id, body, markers=markers)

    monkeypatch.setattr(backend._client, "issue_comment", faulting_comment)

    first = _close_issue_store_unit(
        backend,
        {"unitId": tasks_unit, "artifactType": "tasks", "bodyPath": tasks_path},
        dry_run=False,
    )
    assert first["verdict"] == "fail", first
    assert first.get("error") == "freeze-repin-failed"
    assert first.get("partialApply") is True
    assert first.get("closedOk") is True
    assert backend._lookup_record(tasks_unit, tasks_path).state == "closed"

    repair = _close_issue_store_unit(
        backend,
        {"unitId": tasks_unit, "artifactType": "tasks", "bodyPath": tasks_path},
        dry_run=False,
    )
    assert repair["verdict"] == "pass", repair
    assert repair.get("hash")
    latest = parse_freeze_record_hash(backend._lookup_record(tasks_unit, tasks_path).comments)
    assert latest == repair["hash"]
    got = backend.get(tasks_unit, tasks_path)
    assert got.verdict == "ok"
    assert got.hash == latest
