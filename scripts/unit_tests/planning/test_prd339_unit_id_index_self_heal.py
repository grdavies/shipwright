"""PRD 339 R39 — unit-id marker reuse refusal + index self-heal."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from planning.backends.issues import IssueStoreBackend
from planning.backends.issues_helpers import (
    ISSUE_UNIT_INDEX,
    ISSUE_UNIT_INDEX_AUDIT,
    issue_index_key,
    load_issue_unit_index,
    self_heal_issue_unit_index,
)
from planning_canonical import compose_issue_body


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _cfg(project_key: str = "r39-heal") -> dict:
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


def test_r39_unit_id_marker_reuse_refused_and_index_self_heals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R39 — put refuses cross-type unit-id reuse; self-heal drops polluted index rows."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    _init_repo(tmp_path)
    project_key = "r39-heal"
    (tmp_path / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_cfg(project_key)), encoding="utf-8"
    )
    backend = IssueStoreBackend(tmp_path, _cfg(project_key))

    shared_unit = "339-prd-planning-store-correctness-provider-expansion"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        shared_unit,
        (
            "---\n"
            f"id: {shared_unit}\n"
            "type: prd\n"
            "status: proposed\n"
            "---\n"
            "# PRD\n"
        ),
    )
    prd = backend._client.issue_create(
        title="PRD 339",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{shared_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=shared_unit,
    )
    (tmp_path / ISSUE_UNIT_INDEX).write_text(
        json.dumps({"version": 1, "units": {issue_index_key(project_key, shared_unit): prd.id}}),
        encoding="utf-8",
    )

    tasks_content = (
        "---\n"
        f"id: {shared_unit}\n"
        "type: tasks\n"
        "status: proposed\n"
        "---\n"
        "# Tasks wrongly reusing PRD unit id\n"
    )
    with pytest.raises(SystemExit) as exc:
        backend.put(shared_unit, f"docs/prds/{shared_unit}/tasks.md", tasks_content)
    assert exc.value.code in (2, 20)

    # Pollute index with a stale orphan issue id, then heal.
    ghost_id = "ghost-issue-404"
    index_path = tmp_path / ISSUE_UNIT_INDEX
    index = load_issue_unit_index(tmp_path)
    index[issue_index_key(project_key, "orphan-unit")] = ghost_id
    index_path.write_text(json.dumps({"version": 1, "units": index}), encoding="utf-8")

    def _resolve(issue_id: str):
        if issue_id == ghost_id:
            return None
        try:
            return backend._client.issue_get(issue_id)
        except Exception:
            return None

    healed = self_heal_issue_unit_index(
        tmp_path,
        project_key=project_key,
        resolve_record=_resolve,
        record_unit_id=lambda rec: str(getattr(rec, "unit_id", "") or ""),
        record_artifact_type=lambda rec: str(getattr(rec, "artifact_type", "") or ""),
    )
    assert healed["removedCount"] >= 1
    assert ghost_id not in load_issue_unit_index(tmp_path).values()
    audit = tmp_path / ISSUE_UNIT_INDEX_AUDIT
    assert audit.is_file()
    assert "unit-index-self-heal" in audit.read_text(encoding="utf-8")
