"""PRD 275 R2/R3 — close re-pins freeze hash; get after close does not tamper."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from planning_canonical import FROZEN_LABEL, parse_freeze_record_hash
from planning_store import IssueStoreBackend, _default_body_path
from planning_store_facade import _close_issue_store_unit


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _cfg(project_key: str = "close-repin-275") -> dict:
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


def _fixture_frozen_tasks(
    backend: IssueStoreBackend,
    *,
    project_key: str,
    prd_unit: str,
    tasks_unit: str,
) -> tuple[str, str]:
    prd_path = _default_body_path(prd_unit, "prd")
    tasks_path = _default_body_path(tasks_unit, "tasks")
    brainstorm_unit = f"brainstorm-2026-08-17-{project_key}"
    brainstorm_path = _default_body_path(brainstorm_unit, "brainstorm")

    brainstorm_body = (
        f"---\nid: {brainstorm_unit}\ntype: brainstorm\nstatus: draft\nvisibility: public\n---\n"
        f"# Brainstorm\n\nRationale.\n"
    )
    assert backend.put(brainstorm_unit, brainstorm_path, brainstorm_body).verdict == "ok"

    prd_body = (
        f"---\nid: {prd_unit}\ntype: prd\nstatus: draft\nvisibility: public\n"
        f"brainstorm: {brainstorm_path}\n---\n"
        f"# PRD close re-pin\n\nBody.\n"
    )
    assert backend.put(prd_unit, prd_path, prd_body).verdict == "ok"

    tasks_body = (
        f"---\nid: {tasks_unit}\ntype: tasks\nstatus: draft\nvisibility: public\nprd: {prd_unit}\n---\n"
        f"# Tasks\n\n- [ ] 1.1 Item\n"
    )
    assert backend.put(tasks_unit, tasks_path, tasks_body).verdict == "ok"

    for unit, path in (
        (brainstorm_unit, brainstorm_path),
        (prd_unit, prd_path),
        (tasks_unit, tasks_path),
    ):
        out = backend.freeze(unit, path, distill=False)
        assert out["verdict"] == "ok", out
        assert out.get("hash")

    return prd_path, tasks_path


def test_close_appends_newest_freeze_hash_with_state_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 — after close, newest sw-freeze-record matches post-close hash."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "close-repin-275-r1"
    cfg = _cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "275-prd-close-repin-r1"
    tasks_unit = "tasks-275-close-repin-r1"
    backend = IssueStoreBackend(root, cfg)
    _prd_path, tasks_path = _fixture_frozen_tasks(
        backend, project_key=project_key, prd_unit=prd_unit, tasks_unit=tasks_unit
    )

    record = backend._lookup_record(tasks_unit, tasks_path)
    assert FROZEN_LABEL in record.labels
    pre_hash = parse_freeze_record_hash(record.comments)
    assert pre_hash

    closed = _close_issue_store_unit(
        backend,
        {"unitId": tasks_unit, "artifactType": "tasks", "bodyPath": tasks_path},
        dry_run=False,
    )
    assert closed["verdict"] == "pass", closed
    assert closed.get("hash")
    assert closed["hash"] != pre_hash

    after = backend._lookup_record(tasks_unit, tasks_path)
    assert after.state == "closed"
    latest = parse_freeze_record_hash(after.comments)
    assert latest == closed["hash"]
    current = backend.verify_frozen_hash(tasks_unit, tasks_path)
    assert current["hash"] == latest


def test_get_after_close_no_tamper_from_close_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 — get succeeds after close; no tamper solely from close mutation."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "close-repin-275-r2"
    cfg = _cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "275-prd-close-repin-r2"
    tasks_unit = "tasks-275-close-repin-r2"
    backend = IssueStoreBackend(root, cfg)
    _prd_path, tasks_path = _fixture_frozen_tasks(
        backend, project_key=project_key, prd_unit=prd_unit, tasks_unit=tasks_unit
    )

    closed = _close_issue_store_unit(
        backend,
        {"unitId": tasks_unit, "artifactType": "tasks", "bodyPath": tasks_path},
        dry_run=False,
    )
    assert closed["verdict"] == "pass", closed

    got = backend.get(tasks_unit, tasks_path)
    assert got.verdict == "ok", got
    assert got.hash == closed["hash"]


def test_freeze_close_get_success_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R3 — freeze → closeout close → get with matching latest freeze hash."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "close-repin-275-r3"
    cfg = _cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "275-prd-close-repin-r3"
    tasks_unit = "tasks-275-close-repin-r3"
    backend = IssueStoreBackend(root, cfg)
    prd_path, tasks_path = _fixture_frozen_tasks(
        backend, project_key=project_key, prd_unit=prd_unit, tasks_unit=tasks_unit
    )

    for unit, path, artifact in (
        (prd_unit, prd_path, "prd"),
        (tasks_unit, tasks_path, "tasks"),
    ):
        out = _close_issue_store_unit(
            backend,
            {"unitId": unit, "artifactType": artifact, "bodyPath": path},
            dry_run=False,
        )
        assert out["verdict"] == "pass", out
        got = backend.get(unit, path)
        assert got.verdict == "ok"
        assert got.hash == out["hash"]
        assert parse_freeze_record_hash(backend._lookup_record(unit, path).comments) == got.hash
