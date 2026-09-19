"""PRD 363 R10 — live prove after package install (hermetic scope + issue-store path)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_facade_pilot as pilot
import planning_store as ps
from credentials.selector_store import SelectorEntry
from issues_lib import FixtureIssuesStore
from planning.backends.issues import IssueStoreBackend
from planning_linear_client import LinearIssuesClient


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)


def _linear_cfg(project_key: str = "live-pilot") -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": project_key,
                "issues": {"teamKey": "TIE", "teamId": "team_TIE"},
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
            }
        },
        "host": {"provider": "github"},
    }


def test_scope_fails_out_of_scope_project(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = SelectorEntry(
        ref="planning-work",
        backend="environment",
        provider="linear",
        hostname=None,
        account=None,
        allowed_repos=("grdavies/tierforge",),
        allowed_project_ids=("allowed-only",),
        allowed_endpoints=("https://api.linear.app/graphql",),
    )
    monkeypatch.setattr(pilot, "_selector_entry_for_ref", lambda _ref: entry)
    scope = pilot._validate_pilot_scope(
        {
            "projectId": "tierforge",
            "repoSlug": "grdavies/tierforge",
            "credentialRef": "planning-work",
        },
        credential_ref="planning-work",
    )
    assert scope["verdict"] == "fail"
    assert scope["error"] == "pilot-project-out-of-scope"


def test_scope_fails_out_of_scope_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = SelectorEntry(
        ref="planning-work",
        backend="environment",
        provider="linear",
        hostname=None,
        account=None,
        allowed_repos=("grdavies/tierforge",),
        allowed_project_ids=("tierforge",),
        allowed_endpoints=("https://example.com/graphql",),
    )
    monkeypatch.setattr(pilot, "_selector_entry_for_ref", lambda _ref: entry)
    scope = pilot._validate_pilot_scope(
        {
            "projectId": "tierforge",
            "repoSlug": "grdavies/tierforge",
            "credentialRef": "planning-work",
        },
        credential_ref="planning-work",
    )
    assert scope["verdict"] == "fail"
    assert scope["error"] == "pilot-endpoint-out-of-scope"


def test_scope_fails_out_of_scope_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    entry = SelectorEntry(
        ref="planning-work",
        backend="environment",
        provider="linear",
        hostname=None,
        account=None,
        allowed_repos=("other/repo",),
        allowed_project_ids=("tierforge",),
        allowed_endpoints=("https://api.linear.app/graphql",),
    )
    monkeypatch.setattr(pilot, "_selector_entry_for_ref", lambda _ref: entry)
    scope = pilot._validate_pilot_scope(
        {
            "projectId": "tierforge",
            "repoSlug": "grdavies/tierforge",
            "credentialRef": "planning-work",
        },
        credential_ref="planning-work",
    )
    assert scope["verdict"] == "fail"
    assert scope["error"] == "pilot-repo-out-of-scope"


def test_stuck_issue_requires_put_incomplete_label(tmp_path: Path) -> None:
    store = FixtureIssuesStore(tmp_path / "issues-fixture.json")
    record = store.create(
        title="stuck",
        body="partial",
        labels=["sw:pilot"],
        project_key="pilot",
        artifact_type="gap",
        unit_id="tie-8-stub",
    )
    client = LinearIssuesClient(
        tmp_path,
        cfg=_linear_cfg()["planning"]["store"],
        fixture_store=store,
    )
    check = pilot._check_stuck_issue_put_incomplete(client, record.id)
    assert check["verdict"] == "fail"
    assert check["error"] == "stuck-issue-not-put-incomplete"
    record = store.update(
        record.id,
        labels=sorted(set(record.labels) | {ps.PUT_INCOMPLETE_LABEL}),
    )
    check_ok = pilot._check_stuck_issue_put_incomplete(client, record.id)
    assert check_ok["verdict"] == "ok"


def test_issue_store_prove_clears_put_incomplete_on_chunked_put(
    tmp_path: Path, repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_repo(tmp_path)
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.chdir(tmp_path)
    cfg = _linear_cfg("prove-r10")
    (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    backend = IssueStoreBackend(tmp_path, cfg)
    synthetic = pilot.live_facade_pilot_synthetic_body(repo_root)
    unit_id = "live-facade-pilot"
    body_path = f"docs/planning/{unit_id}/body.md"
    operator = pilot._operator_gap_content(unit_id, synthetic)
    updated = pilot._operator_gap_content(unit_id, f"{synthetic}\n\n## pilot-update\n\nedit.")
    dest = tmp_path / "out.md"
    prove = backend.live_facade_issue_store_prove(
        unit_id=unit_id,
        body_path=body_path,
        operator_content=operator,
        updated_operator_content=updated,
        materialize_dest=dest,
    )
    assert "put" in prove["ops"]
    assert "materialize" in prove["ops"]
    assert dest.is_file()
    record = backend._lookup_record(unit_id, body_path)
    assert ps.PUT_INCOMPLETE_LABEL not in record.labels
