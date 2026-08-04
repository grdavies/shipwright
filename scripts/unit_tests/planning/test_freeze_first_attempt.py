"""PRD 093 R2 — freeze succeeds on first attempt against fixture issue-store units."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from planning_canonical import FROZEN_LABEL, build_edges_block
from planning_store import IssueStoreBackend, _default_body_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "freeze-first-093") -> dict:
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


def _fixture_doc_set(
    backend: IssueStoreBackend,
    *,
    project_key: str,
    prd_unit: str,
    brainstorm_unit: str,
    tasks_unit: str,
) -> tuple[str, str, str]:
    prd_path = _default_body_path(prd_unit, "prd")
    brainstorm_path = _default_body_path(brainstorm_unit, "brainstorm")
    tasks_path = _default_body_path(tasks_unit, "tasks")

    brainstorm_body = (
        f"---\nid: {brainstorm_unit}\ntype: brainstorm\nstatus: draft\nvisibility: public\n---\n"
        f"# Brainstorm for freeze smoke\n\nDistilled rationale without transcript markers.\n"
        + build_edges_block([{"rel": "produces", "target": prd_unit}])
    )
    assert backend.put(brainstorm_unit, brainstorm_path, brainstorm_body).verdict == "ok"

    prd_body = (
        f"---\nid: {prd_unit}\ntype: prd\nstatus: draft\nvisibility: public\n---\n"
        f"# PRD freeze smoke\n\nMinimal PRD body for first-attempt freeze convergence.\n"
    )
    assert backend.put(prd_unit, prd_path, prd_body).verdict == "ok"

    tasks_body = (
        f"---\nid: {tasks_unit}\ntype: tasks\nstatus: draft\nvisibility: public\nprd: {prd_unit}\n---\n"
        f"# Tasks\n\n- [ ] 1.1 Smoke task\n"
    )
    assert backend.put(tasks_unit, tasks_path, tasks_body).verdict == "ok"

    return prd_path, brainstorm_path, tasks_path


def test_freeze_succeeds_first_attempt_for_brainstorm_prd_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R2 — IssueStoreBackend.freeze() converges on first call (no revision-conflict retry)."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "freeze-first-093"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")

    prd_unit = "093-prd-freeze-etag-retry-and-absorb-edge-preservation"
    brainstorm_unit = "2026-08-04-freeze-first-attempt-smoke"
    tasks_unit = "tasks-093-prd-freeze-etag-retry-and-absorb-edge-preservation"

    backend = IssueStoreBackend(root, cfg)
    prd_path, brainstorm_path, tasks_path = _fixture_doc_set(
        backend,
        project_key=project_key,
        prd_unit=prd_unit,
        brainstorm_unit=brainstorm_unit,
        tasks_unit=tasks_unit,
    )

    lock_calls = 0
    label_calls = 0
    original_lock = backend._client.issue_lock
    original_label = backend._client.issue_label

    def counting_lock(issue_id: str, *, if_match: str | None = None):
        nonlocal lock_calls
        lock_calls += 1
        return original_lock(issue_id, if_match=if_match)

    def counting_label(issue_id: str, labels: list[str], *, if_match: str | None = None):
        nonlocal label_calls
        label_calls += 1
        return original_label(issue_id, labels, if_match=if_match)

    monkeypatch.setattr(backend._client, "issue_lock", counting_lock)
    monkeypatch.setattr(backend._client, "issue_label", counting_label)

    prd_result = backend.freeze(prd_unit, prd_path, distill=True)
    assert prd_result["verdict"] == "ok"
    assert prd_result.get("locked") is True
    assert prd_result.get("hash")

    tasks_result = backend.freeze(tasks_unit, tasks_path, distill=False)
    assert tasks_result["verdict"] == "ok"
    assert tasks_result.get("locked") is True

    brainstorm_result = backend.freeze(brainstorm_unit, brainstorm_path, distill=False)
    assert brainstorm_result["verdict"] == "ok"
    assert brainstorm_result.get("locked") is True

    assert lock_calls == 3
    assert label_calls >= 3

    store_path = root / ".cursor" / "hooks" / "state" / "issue-store-fixture.json"
    fixture = json.loads(store_path.read_text(encoding="utf-8"))
    for unit in (prd_unit, tasks_unit, brainstorm_unit):
        record = next(
            rec for rec in fixture["issues"].values() if rec.get("unit_id") == unit
        )
        assert record.get("locked") is True
        assert FROZEN_LABEL in record.get("labels", [])
        if unit == prd_unit:
            freeze_hash = prd_result["hash"]
            comment_bodies = [c.get("body", "") for c in record.get("comments", [])]
            assert any(freeze_hash in body for body in comment_bodies)
