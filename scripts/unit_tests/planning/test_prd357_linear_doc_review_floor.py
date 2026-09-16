"""PRD 357 R15/R6 — Linear document-review 341 floor (whoami, author_id, pagination)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_lib
import planning_linear_client as plc
from issues_broker import IssueCommentAuthorshipMismatch
from planning_canonical import BODY_SIZE_LIMIT, LINEAR_SIZE_PIN, reassemble_body
from planning_doc_review_transport import (
    DOC_REVIEW_MANDATORY_CAPABILITIES,
    DOC_REVIEW_PROVIDER_UNSUPPORTED,
    chunk_review_round_body,
    doc_review_capabilities_for,
    inspect_review_round_block,
    missing_doc_review_capabilities,
    provider_unsupported,
    upsert_review_round_block,
)
from planning.doc_review_conformance import DOC_REVIEW_ENABLED_PROVIDERS


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


def _live_client(tmp_path: Path) -> plc.LinearIssuesClient:
    """Construct via fixture so readiness gates skip, then force the live method path."""
    store = issues_lib.FixtureIssuesStore(tmp_path / "linear-doc-review-fixture.json")
    client = plc.LinearIssuesClient(tmp_path, cfg=_cfg(), fixture_store=store)
    client._fixture = None
    return client


def _issue_node(
    issue_id: str,
    *,
    comments: dict[str, Any] | None = None,
    description: str = "# PRD\n",
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "identifier": "ENG-9",
        "title": "PRD",
        "description": description,
        "updatedAt": "2026-01-01T00:00:00.000Z",
        "state": {"id": "state_open", "name": "Todo", "type": "unstarted"},
        "labels": {"nodes": [{"id": "lbl", "name": "sw:prd"}]},
        "comments": comments
        if comments is not None
        else {"nodes": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
        "relations": {"nodes": []},
        "inverseRelations": {"nodes": []},
    }


class TestLinearR15Floor:
    def test_whoami_uses_viewer_id_not_payload_claimed_author(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _live_client(tmp_path)
        calls: list[str] = []

        def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            calls.append(query)
            if "viewer" in query:
                return {"data": {"viewer": {"id": "viewer-brokered-1"}}}
            raise AssertionError(f"unexpected query: {query}")

        monkeypatch.setattr(client, "_gql", fake_gql)
        assert client.authenticated_principal_id() == "viewer-brokered-1"
        assert any("viewer" in q for q in calls)

    def test_whoami_refuses_empty_viewer(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _live_client(tmp_path)

        def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            return {"data": {"viewer": {"id": ""}}}

        monkeypatch.setattr(client, "_gql", fake_gql)
        with pytest.raises(plc.LinearClientError) as exc:
            client.authenticated_principal_id()
        assert exc.value.code == "whoami-unavailable"

    def test_comment_fetch_and_create_include_author_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _live_client(tmp_path)

        def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            if "commentCreate" in query or "CommentCreate" in query:
                return {
                    "data": {
                        "commentCreate": {
                            "success": True,
                            "comment": {
                                "id": "c-created",
                                "body": "hello",
                                "createdAt": "2026-01-01T00:00:00.000Z",
                                "user": {"id": "viewer-brokered-1"},
                            },
                        }
                    }
                }
            comments = {
                "nodes": [
                    {
                        "id": "c1",
                        "body": "fetched",
                        "createdAt": "2026-01-01T00:00:00.000Z",
                        "user": {"id": "user-linear-9"},
                    }
                ],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            }
            return {"data": {"issue": _issue_node("issue_1", comments=comments)}}

        monkeypatch.setattr(client, "_gql", fake_gql)
        record = client.get("issue_1")
        assert record.comments[0].author_id == "user-linear-9"
        created = client.add_comment("issue_1", "hello", author_id="viewer-brokered-1")
        assert created.author_id == "viewer-brokered-1"

    def test_create_author_mismatch_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _live_client(tmp_path)

        def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            return {
                "data": {
                    "commentCreate": {
                        "success": True,
                        "comment": {
                            "id": "c-created",
                            "body": "hello",
                            "createdAt": "2026-01-01T00:00:00.000Z",
                            "user": {"id": "other-user"},
                        },
                    }
                }
            }

        monkeypatch.setattr(client, "_gql", fake_gql)
        with pytest.raises(IssueCommentAuthorshipMismatch):
            client.add_comment("issue_1", "hello", author_id="viewer-brokered-1")

    def test_comments_complete_false_when_has_next_page(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _live_client(tmp_path)
        monkeypatch.setattr(plc, "MAX_SEARCH_PAGES", 1)

        def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            comments = {
                "nodes": [
                    {
                        "id": "c1",
                        "body": "page-1",
                        "createdAt": "2026-01-01T00:00:00.000Z",
                        "user": {"id": "u1"},
                    }
                ],
                "pageInfo": {"hasNextPage": True, "endCursor": "cursor_1"},
            }
            return {"data": {"issue": _issue_node("issue_1", comments=comments)}}

        monkeypatch.setattr(client, "_gql", fake_gql)
        record = client.get("issue_1")
        assert record.comments_complete is False

    def test_paginated_comments_walk_until_complete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _live_client(tmp_path)
        pages: list[str | None] = []

        def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
            variables = dict(variables or {})
            after = variables.get("after")
            pages.append(after)
            if after is None:
                comments = {
                    "nodes": [
                        {
                            "id": "c1",
                            "body": "p1",
                            "createdAt": "2026-01-01T00:00:00.000Z",
                            "user": {"id": "u1"},
                        }
                    ],
                    "pageInfo": {"hasNextPage": True, "endCursor": "cursor_1"},
                }
            else:
                comments = {
                    "nodes": [
                        {
                            "id": "c2",
                            "body": "p2",
                            "createdAt": "2026-01-01T00:00:01.000Z",
                            "user": {"id": "u2"},
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            return {"data": {"issue": _issue_node("issue_1", comments=comments)}}

        monkeypatch.setattr(client, "_gql", fake_gql)
        record = client.get("issue_1")
        assert [c.id for c in record.comments] == ["c1", "c2"]
        assert record.comments_complete is True
        assert None in pages
        assert "cursor_1" in pages

    def test_degraded_lock_does_not_advertise_authorship_or_body_drift(self) -> None:
        lock = plc.lock_capability()
        assert lock["capability"] == "degraded"
        assert lock.get("native") is False
        caps = plc.linear_doc_review_capabilities()
        for name in DOC_REVIEW_MANDATORY_CAPABILITIES:
            assert caps[name] is True, name
        # Lock is not a substitute: the lock payload carries no authorship/body-drift flags.
        assert "verifiableAuthorPrincipal" not in lock
        assert "completeFullBody" not in lock

    def test_missing_floor_keeps_provider_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(plc, "linear_r15_floor_present", lambda: False)
        caps = plc.linear_doc_review_capabilities()
        for name in DOC_REVIEW_MANDATORY_CAPABILITIES:
            assert caps[name] is False
        monkeypatch.setattr(
            plc,
            "linear_doc_review_capabilities",
            lambda: {
                "post": False,
                "stableIds": False,
                "verifiableAuthorPrincipal": False,
                "stableApplicationId": False,
                "nativeRevision": False,
                "completeFullBody": False,
                "completePagination": False,
            },
        )
        missing = missing_doc_review_capabilities("linear")
        assert missing
        out = provider_unsupported(provider="linear")
        assert out["error"] == DOC_REVIEW_PROVIDER_UNSUPPORTED


class TestLinearR6Enablement:
    def test_linear_advertises_mandatory_capabilities_after_floor(self) -> None:
        assert plc.linear_r15_floor_present() is True
        caps = doc_review_capabilities_for("linear")
        assert missing_doc_review_capabilities("linear") == []
        for name in DOC_REVIEW_MANDATORY_CAPABILITIES:
            assert caps[name] is True, name
        assert "linear" in DOC_REVIEW_ENABLED_PROVIDERS

    def test_unshipped_providers_stay_unsupported(self) -> None:
        for provider in ("gitlab-issues", "jira", "notion", "none"):
            assert provider not in DOC_REVIEW_ENABLED_PROVIDERS
            assert missing_doc_review_capabilities(provider)

    def test_linear_overflow_obeys_r10_not_github_fence_in_one_comment(self) -> None:
        prefix = "<!-- sw-unit-id: u -->\n# PRD\n\nShort body.\n"
        block = {
            "roundId": "r-linear-overflow",
            "status": "open",
            "unitId": "u",
            "issueId": "1",
            "pins": [{"persona": "security", "commentId": "c1"}],
            "note": "n" * (BODY_SIZE_LIMIT + 2048),
        }
        full = upsert_review_round_block(prefix, block)
        assert len(full.encode("utf-8")) > BODY_SIZE_LIMIT
        github_head, github_extras = chunk_review_round_body(full)
        linear_head, linear_extras = chunk_review_round_body(full, provider="linear")
        assert github_extras
        github_overflow = github_extras[0].body.encode("utf-8")
        comment_limit = int(LINEAR_SIZE_PIN["commentLimit"])
        # GitHub fence-in-one-comment may exceed Linear's R10 comment pin.
        assert len(github_overflow) > comment_limit
        assert linear_extras
        for extra in linear_extras:
            assert len(extra.body.encode("utf-8")) <= comment_limit
        logical = reassemble_body(linear_head, linear_extras)
        manifest, err = inspect_review_round_block(logical)
        assert err is None, err
        assert manifest["roundId"] == "r-linear-overflow"

    def test_linear_id_rewrite_is_not_comment_drift(self) -> None:
        """Synthetic chunk ids rewritten to real comment ids stay findable, not drifted."""
        from planning_canonical import rewrite_chunk_manifest_ids

        prefix = "<!-- sw-unit-id: u -->\n# PRD\n\n"
        padding = "para\n" * ((BODY_SIZE_LIMIT // 5) + 8)
        block = {
            "roundId": "r-rewrite",
            "status": "open",
            "unitId": "u",
            "issueId": "1",
            "pins": [{"persona": "coherence", "commentId": "finding-1"}],
        }
        full = upsert_review_round_block(prefix + padding, block)
        head, extras = chunk_review_round_body(full, provider="linear")
        assert extras
        posted_ids = [f"lin-comment-{i}" for i in range(len(extras))]
        rewritten = rewrite_chunk_manifest_ids(head, posted_ids)
        for extra in extras:
            extra.id = posted_ids[extras.index(extra)] if extra.id.startswith("chunk-") else extra.id
        logical = reassemble_body(rewritten, extras)
        manifest, err = inspect_review_round_block(logical)
        assert err is None, err
        assert manifest["roundId"] == "r-rewrite"
        assert '"commentId": "chunk-0"' not in rewritten
        # Persona pin comment ids are unchanged by overflow id rewrite.
        assert manifest["pins"][0]["commentId"] == "finding-1"
