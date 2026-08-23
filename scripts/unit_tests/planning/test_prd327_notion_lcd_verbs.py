"""PRD 327 R2 — NotionIssuesClient LCD verbs against fixture store (hermetic)."""

from __future__ import annotations

from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore, IssueRevisionConflict
from planning_canonical import FROZEN_LABEL, canonical_hash
from planning_notion_client import NotionIssuesClient, snapshot_from_fixture_record


def _fixture_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, FixtureIssuesStore]:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "workflow.config.json").write_text(
        json_dumps(
            {
                "planning": {
                    "store": {
                        "backend": "issue-store",
                        "projectKey": "acme",
                        "issuesProvider": "notion",
                        "issues": {
                            "notionDatabaseId": "db-fixture-00000000000000000000000000000001",
                            "tokenEnv": "ISSUES_NOTION_TOKEN",
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    return root, store


def json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, indent=2) + "\n"


def test_lcd_create_get_update_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, store = _fixture_repo(tmp_path, monkeypatch)
    client = NotionIssuesClient(root, fixture_store=store)
    created = client.create(
        title="[acme] prd:327-demo",
        body="# Demo\n\nBody text.",
        labels=["sw:prd"],
        project_key="acme",
        artifact_type="prd",
        unit_id="prd-327-demo",
    )
    fetched = client.get(created.id)
    assert fetched.title == created.title
    assert fetched.body == created.body
    updated = client.update(
        created.id,
        title="[acme] prd:327-demo-updated",
        if_match=fetched.etag,
    )
    assert updated.title.endswith("updated")
    matches = client.search(project_key="acme", unit_id="prd-327-demo")
    assert len(matches) == 1
    assert matches[0].id == created.id


def test_lock_degraded_freeze_record(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, store = _fixture_repo(tmp_path, monkeypatch)
    client = NotionIssuesClient(root, fixture_store=store)
    created = client.create(
        title="[acme] gap:327-lock",
        body="Freeze me.",
        labels=["sw:gap"],
        project_key="acme",
        artifact_type="gap",
        unit_id="gap-327-lock",
    )
    locked = client.lock(created.id, if_match=created.etag)
    assert FROZEN_LABEL in locked.labels
    assert locked.locked
    assert any("sw-freeze-record" in c.markers for c in locked.comments)
    expected_hash = canonical_hash(snapshot_from_fixture_record(locked))
    freeze_comment = next(c for c in locked.comments if "sw-freeze-record" in c.markers)
    assert expected_hash in freeze_comment.body


def test_etag_conflict_on_stale_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, store = _fixture_repo(tmp_path, monkeypatch)
    client = NotionIssuesClient(root, fixture_store=store)
    created = client.create(
        title="[acme] task:327-etag",
        body="Stale token test.",
        labels=["sw:task"],
        project_key="acme",
        artifact_type="task",
        unit_id="task-327-etag",
    )
    stale = created.etag
    store.update(created.id, body="Changed elsewhere.", if_match=stale)
    with pytest.raises(IssueRevisionConflict) as exc:
        client.update(created.id, body="Attempt stale.", if_match=stale)
    assert exc.value.args[0] in {"etag-conflict", "revision-conflict"}


def test_add_comment_and_set_labels(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root, store = _fixture_repo(tmp_path, monkeypatch)
    client = NotionIssuesClient(root, fixture_store=store)
    created = client.create(
        title="[acme] prd:327-comment",
        body="Comment body.",
        labels=["sw:prd"],
        project_key="acme",
        artifact_type="prd",
        unit_id="prd-327-comment",
    )
    client.add_comment(created.id, "Operator note.", markers=["sw-memory-pointer"])
    labeled = client.set_labels(created.id, labels=["sw:prd", "sw:project:acme"])
    assert "sw:project:acme" in labeled.labels
    record = client.get(created.id)
    assert any("Operator note." in c.body for c in record.comments)
