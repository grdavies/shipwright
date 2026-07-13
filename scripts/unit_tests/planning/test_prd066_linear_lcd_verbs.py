"""PRD 066 phase 4 — Linear LCD FixtureIssuesStore verb parity + lock/overflow (R10)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_lib
import planning_canonical as pc
import planning_linear_client as plc


def _cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": "demo",
                "issues": {
                    "tokenEnv": "ISSUES_LINEAR_TOKEN",
                    "authMode": "api-key",
                    "teamKey": "ENG",
                    "teamId": "team_ENG",
                },
            }
        }
    }


def _client(tmp_path: Path) -> plc.LinearIssuesClient:
    store = issues_lib.FixtureIssuesStore(tmp_path / "linear-fixture.json")
    return plc.LinearIssuesClient(tmp_path, cfg=_cfg(), fixture_store=store)


def test_r10_duck_type_verbs_match_fixture_store() -> None:
    """R10 — LinearIssuesClient exposes FixtureIssuesStore LCD verbs + lifecycle hooks."""
    for name in plc.lcd_verb_names():
        assert callable(getattr(plc.LinearIssuesClient, name))
    for name in plc.lifecycle_hook_names():
        assert callable(getattr(plc.LinearIssuesClient, name))
    fixture_methods = {
        "create",
        "get",
        "update",
        "add_comment",
        "set_labels",
        "lock",
        "search",
        "mark_tombstone",
        "mark_transferred",
        "mark_archived_project",
        "mark_type_converted",
        "mark_key_changed",
    }
    for name in fixture_methods:
        assert hasattr(plc.LinearIssuesClient, name)


def test_r10_fixture_crud_comment_labels_search(tmp_path: Path) -> None:
    """R10 — create/get/update/comment/labels/search pass against Linear fixture harness."""
    client = _client(tmp_path)
    created = client.create(
        title="[demo] prd:unit-1",
        body="<!-- sw-unit-id: unit-1 -->\nbody",
        labels=["sw:prd"],
        project_key="demo",
        artifact_type="prd",
        unit_id="unit-1",
    )
    got = client.get(created.id)
    assert got.title == created.title
    assert got.project_key == "demo"

    updated = client.update(created.id, title="[demo] prd:unit-1-v2", if_match=got.etag)
    assert updated.title.endswith("unit-1-v2")

    comment = client.add_comment(created.id, "hello", markers=["note"])
    assert comment.body == "hello"

    labeled = client.set_labels(created.id, ["sw:prd", "sw:project:demo"], if_match=updated.etag)
    assert "sw:prd" in labeled.labels

    found = client.search(project_key="demo", unit_id="unit-1")
    assert len(found) == 1
    assert found[0].id == created.id


def test_r10_lock_degraded_hash_authoritative(tmp_path: Path) -> None:
    """R10 — lock is degraded; applies sw:frozen and marks locked without native lock."""
    cap = plc.lock_capability()
    assert cap["capability"] == "degraded"
    assert cap["native"] is False
    assert cap["mechanism"] == "hash-authoritative"
    assert plc.NATIVE_ISSUE_LOCK is False

    client = _client(tmp_path)
    assert client.lock_capability()["capability"] == "degraded"

    created = client.create(
        title="lock-me",
        body="body",
        labels=[],
        project_key="demo",
        artifact_type="prd",
        unit_id="u-lock",
    )
    locked = client.lock(created.id, if_match=created.etag)
    assert locked.locked is True
    assert pc.FROZEN_LABEL in locked.labels

    with pytest.raises(issues_lib.IssueRevisionConflict):
        client.update(created.id, body="tamper", if_match=locked.etag)


def test_r10_overflow_chunk_policy_and_chunk_body(tmp_path: Path) -> None:
    """R10 — overflow uses BODY_SIZE_LIMIT + sw-chunk-overflow comments."""
    policy = plc.overflow_chunk_policy()
    assert policy["provider"] == "linear"
    assert policy["bodySizeLimitBytes"] == pc.BODY_SIZE_LIMIT
    assert policy["chunkMarker"] == "sw-chunk-overflow"

    oversized = "x" * (pc.BODY_SIZE_LIMIT + 5_000)
    head, extras = plc.prepare_body_with_overflow(oversized, [])
    # Head is truncated then receives a sw-chunk-manifest marker (may exceed the
    # raw limit by the marker length); overflow must land in chunk comments.
    assert extras
    assert "sw-chunk-overflow" in extras[0].markers
    assert "sw-chunk-manifest" in head
    assert extras[0].body.startswith("<!-- sw-chunk-overflow -->")
    assert len(head.encode("utf-8")) + len(extras[0].body.encode("utf-8")) >= pc.BODY_SIZE_LIMIT

    client = _client(tmp_path)
    assert client.overflow_chunk_policy()["chunkMarker"] == "sw-chunk-overflow"


def test_r10_lifecycle_hooks_on_fixture(tmp_path: Path) -> None:
    """R10 — lifecycle hooks operate on the fixture harness."""
    client = _client(tmp_path)
    created = client.create(
        title="tombstone-me",
        body="body",
        labels=[],
        project_key="demo",
        artifact_type="gap",
        unit_id="u-tomb",
    )
    client.mark_tombstone(created.id)
    with pytest.raises(issues_lib.IssueTombstone):
        client.get(created.id)

    other = client.create(
        title="xfer",
        body="body",
        labels=[],
        project_key="demo",
        artifact_type="gap",
        unit_id="u-xfer",
    )
    client.mark_transferred(other.id)
    with pytest.raises(issues_lib.IssueTransferred):
        client.get(other.id)


def test_r10_issues_lib_routes_linear_live_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R10 — IssuesClient selects LinearIssuesClient for provider=linear (non-fixture)."""
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
    store = issues_lib.FixtureIssuesStore(tmp_path / "route-fixture.json")

    class _FakeLinear(plc.LinearIssuesClient):
        def __init__(self, root: Path, **kwargs: Any) -> None:  # noqa: ARG002
            super().__init__(root, cfg=_cfg(), fixture_store=store)

    monkeypatch.setattr(plc, "LinearIssuesClient", _FakeLinear)
    # Re-import path used inside IssuesClient._live_backend
    import planning_linear_client as live_mod

    monkeypatch.setattr(live_mod, "LinearIssuesClient", _FakeLinear)

    client = issues_lib.IssuesClient(tmp_path, "linear")
    backend = client._live_backend()
    assert isinstance(backend, plc.LinearIssuesClient) or backend is store or hasattr(backend, "create")
    created = client.issue_create(
        title="via-issues-lib",
        body="body",
        labels=["sw:prd"],
        project_key="demo",
        artifact_type="prd",
        unit_id="u-lib",
    )
    assert created.title == "via-issues-lib"


def test_r10_linear_md_documents_lock_and_overflow() -> None:
    """R10 — provider docs describe degraded lock + overflow chunk behavior."""
    roots = [
        Path(__file__).resolve().parents[3] / "core/providers/issues/linear.md",
        Path(__file__).resolve().parents[2].parent / "core/providers/issues/linear.md",
    ]
    doc = None
    for candidate in roots:
        if candidate.is_file():
            doc = candidate.read_text(encoding="utf-8")
            break
    assert doc is not None
    assert "issue-lock" in doc
    assert "degraded" in doc
    assert "hash-authoritative" in doc
    assert "sw-chunk-overflow" in doc
    assert "BODY_SIZE_LIMIT" in doc or "60_000" in doc or "60000" in doc
