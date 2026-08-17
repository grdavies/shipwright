"""PRD 275 phase 1 — provider/scope/auth failures propagate not-ready (R15)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore, IssueCapabilityError, IssuesClient
from planning_canonical import compose_issue_body, type_label
from planning_store import resolve_delivery_linked_units
from planning_store_facade import PlanningIssueRefResolutionError, resolve_planning_issue_ref_to_gap


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "gap-resolver-provider") -> dict:
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


def test_provider_auth_failures_not_silent_skip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R15 — provider errors raise; they are not typed non-gap skips."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-provider"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "275-prd-provider-errors"
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        (
            f"---\nid: {prd_unit}\ntype: prd\nstatus: complete\n"
            f"planningIssues: planning#703\n---\n# PRD\n"
        ),
    )
    prd_rec = store.create(
        title="prd",
        body=prd_body,
        labels=[type_label("prd"), f"sw:unit:{prd_unit}"],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {f"{project_key}:{prd_unit}": prd_rec.id}}),
        encoding="utf-8",
    )

    original_issue_get = IssuesClient.issue_get

    def _raising_issue_get(self, issue_id: str):
        if issue_id == "703":
            raise IssueCapabilityError("auth-scope-denied")
        return original_issue_get(self, issue_id)

    monkeypatch.setattr(IssuesClient, "issue_get", _raising_issue_get)

    with pytest.raises(PlanningIssueRefResolutionError) as exc_info:
        resolve_planning_issue_ref_to_gap(root, cfg, "planning#703")
    assert exc_info.value.error == "issue-capability-error"

    snap = resolve_delivery_linked_units(root, cfg, prd_unit)
    assert snap["verdict"] == "not-ready", snap
    assert snap["error"] == "issue-capability-error"


def test_nongap_numeric_returns_none_no_raise(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R5 — positive non-gap classification skips without raise."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    project_key = "gap-resolver-nongap"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")

    prd_unit = "275-prd-nongap-ref"
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
    prd_rec.number = 704
    store._issues[prd_rec.id] = prd_rec
    store._persist()

    skip_meta: dict[str, str] = {}
    assert resolve_planning_issue_ref_to_gap(root, cfg, "704", skip_meta=skip_meta) is None
    assert skip_meta["reason"] == "planning-issue-nongap"
    assert skip_meta["artifactType"] == "prd"
