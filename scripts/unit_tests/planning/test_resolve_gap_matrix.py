"""PRD 275 phase 1 — resolver matrix: gap, non-gap, conflict, provider, no-catalog (R17)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from issues_lib import FixtureIssuesStore, IssueCapabilityError, IssuesClient
from planning_canonical import compose_issue_body, type_label
from planning_store_facade import PlanningIssueRefResolutionError, resolve_planning_issue_ref_to_gap


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "gap-resolver-matrix") -> dict:
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


def _fixture_store(root: Path, project_key: str) -> FixtureIssuesStore:
    return FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")


def test_resolver_matrix_gap_prd_tasks_conflict_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R17 — matrix covers positive gap, numeric non-gap, conflict, provider-error, no-catalog."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-matrix"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = _fixture_store(root, project_key)

    gap_unit = "gap-275-matrix"
    gap_body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: open\nrelated: planning#710\n---\n# gap\n",
    )
    gap_rec = store.create(
        title="gap",
        body=gap_body,
        labels=[type_label("gap"), f"sw:unit:{gap_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    gap_rec.number = 710
    store._issues[gap_rec.id] = gap_rec

    prd_unit = "275-prd-matrix"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n---\n# PRD\n",
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    prd_rec.number = 711
    store._issues[prd_rec.id] = prd_rec

    conflict_unit = "gap-275-matrix-conflict"
    conflict_body = compose_issue_body(
        project_key,
        "gap",
        conflict_unit,
        f"---\nid: {conflict_unit}\ntype: prd\nstatus: open\n---\n# conflict\n",
    )
    conflict_rec = store.create(
        title="conflict",
        body=conflict_body,
        labels=[type_label("gap"), f"sw:unit:{conflict_unit}"],
        project_key=project_key,
        artifact_type="gap",
        unit_id=conflict_unit,
    )
    conflict_rec.number = 712
    store._issues[conflict_rec.id] = conflict_rec
    store._persist()

    assert resolve_planning_issue_ref_to_gap(root, cfg, "planning#710") == gap_unit

    skip_meta: dict[str, str] = {}
    assert resolve_planning_issue_ref_to_gap(root, cfg, "711", skip_meta=skip_meta) is None
    assert skip_meta["reason"] == "planning-issue-nongap"

    with pytest.raises(PlanningIssueRefResolutionError) as exc_info:
        resolve_planning_issue_ref_to_gap(root, cfg, "712")
    assert exc_info.value.error == "artifact-type-conflict"

    from planning_store import IssueStoreBackend

    original_issue_get = IssuesClient.issue_get

    def _provider_fail_issue_get(self, issue_id: str):
        if issue_id == "713":
            raise IssueCapabilityError("simulated-auth-failure")
        return original_issue_get(self, issue_id)

    monkeypatch.setattr(IssuesClient, "issue_get", _provider_fail_issue_get)
    with pytest.raises(PlanningIssueRefResolutionError) as exc_info:
        resolve_planning_issue_ref_to_gap(root, cfg, "713")
    assert exc_info.value.error == "issue-capability-error"

    backend = IssueStoreBackend(root, cfg)
    no_search_client = MagicMock()
    no_search_client.issue_get = backend._client.issue_get
    no_search_client.issue_search = None
    no_search_backend = IssueStoreBackend(root, cfg)
    monkeypatch.setattr(no_search_backend, "_client", no_search_client)

    unresolved_meta: dict[str, str] = {}
    assert (
        resolve_planning_issue_ref_to_gap(
            root,
            cfg,
            "planning#99999",
            backend=no_search_backend,
            skip_meta=unresolved_meta,
        )
        is None
    )
    assert unresolved_meta["reason"] == "planning-issue-unresolved"
