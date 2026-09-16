"""PRD 357 R15/R6 — Jira and Notion document-review 341 floor plus TR5 markers."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_lib
import planning_jira_client as pjc
import planning_notion_client as pnc
from credentials.model import CredentialRef, Principal, Resolution, ResolvedToken, Secret
from issues_broker import IssueCommentAuthorshipMismatch
from planning_jira_canonical import JIRA_CLOUD_DESCRIPTION_LIMIT, adf_to_markdown
from planning_doc_review_transport import (
    DOC_REVIEW_MANDATORY_CAPABILITIES,
    DOC_REVIEW_PAYLOAD_TOO_LARGE,
    DOC_REVIEW_PROVIDER_UNSUPPORTED,
    build_doc_review_comment_body,
    doc_review_capabilities_for,
    inspect_review_round_block,
    missing_doc_review_capabilities,
    parse_doc_review_comment,
    provider_unsupported,
    upsert_review_round_block,
)
from planning.doc_review_conformance import DOC_REVIEW_ENABLED_PROVIDERS


def _sample_findings() -> dict[str, Any]:
    return {
        "reviewer": "coherence",
        "findings": [
            {
                "title": "Example finding",
                "severity": "P2",
                "section": "Requirements",
                "why_it_matters": "Clarity",
                "finding_type": "omission",
                "autofix_class": "manual",
                "suggested_fix": "Clarify requirement",
                "confidence": 75,
                "evidence": ["ambiguous wording"],
            }
        ],
        "residual_risks": [],
        "deferred_questions": [],
    }


def _jira_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "jira",
                "projectKey": "DEMO",
                "issues": {
                    "endpoint": "https://example.atlassian.net",
                    "flavor": "cloud",
                    "tokenEnv": "ISSUES_JIRA_TOKEN",
                    "emailEnv": "ISSUES_JIRA_EMAIL",
                },
            }
        },
        "host": {
            "provider": "github",
            "ssrfAllowlist": ["example.atlassian.net", "atlassian.net"],
        },
    }


def _jira_live_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> pjc.JiraIssuesClient:
    cfg = _jira_cfg()
    monkeypatch.setattr(pjc, "load_workflow_config", lambda _root: cfg)
    monkeypatch.setattr(pjc, "resolve_jira_api_project_key", lambda *_a, **_k: "DEMO")
    credential = Resolution.resolved(
        CredentialRef("jira-work"),
        ResolvedToken(Secret("jira-test-token"), Principal(profile="work", account="bot@example.com")),
    )
    return pjc.JiraIssuesClient(tmp_path, credential=credential)


def _jira_issue_payload(*, comments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    comments = list(comments or [])
    return {
        "key": "DEMO-9",
        "fields": {
            "summary": "PRD",
            "description": {
                "type": "doc",
                "version": 1,
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "# PRD"}]}],
            },
            "labels": ["sw:prd"],
            "status": {"statusCategory": {"key": "new"}},
            "updated": "2026-01-01T00:00:00.000+0000",
            "comment": {
                "comments": comments,
                "maxResults": len(comments),
                "total": len(comments),
                "startAt": 0,
            },
            "issuelinks": [],
        },
    }


def _jira_comment(*, comment_id: str, body: str, account_id: str) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": {
            "type": "doc",
            "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": body}]}],
        },
        "created": "2026-01-01T00:00:00.000+0000",
        "author": {"accountId": account_id, "displayName": "Bot"},
    }


def _notion_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "notion",
                "projectKey": "demo",
                "issues": {
                    "notionDatabaseId": "db-fixture-00000000000000000000000000000001",
                    "tokenEnv": "ISSUES_NOTION_TOKEN",
                },
            }
        }
    }


def _notion_live_client(tmp_path: Path) -> pnc.NotionIssuesClient:
    store = issues_lib.FixtureIssuesStore(tmp_path / "notion-doc-review-fixture.json")
    client = pnc.NotionIssuesClient(tmp_path, cfg=_notion_cfg(), fixture_store=store)
    client._fixture = None
    client._token = "notion-test-token"
    return client


class TestJiraR15Floor:
    def test_whoami_uses_myself_account_id_not_payload_claimed_author(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _jira_live_client(tmp_path, monkeypatch)
        urls: list[str] = []

        def fake_http(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
            urls.append(url)
            assert "/myself" in url
            return {"accountId": "jira-brokered-1", "displayName": "Bot"}

        monkeypatch.setattr(client, "_http_json", fake_http)
        assert client.authenticated_principal_id() == "jira-brokered-1"
        assert any("/myself" in url for url in urls)

    def test_whoami_refuses_empty_account(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _jira_live_client(tmp_path, monkeypatch)

        def fake_http(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
            return {"accountId": "", "name": ""}

        monkeypatch.setattr(client, "_http_json", fake_http)
        with pytest.raises(pjc.JiraClientError) as exc:
            client.authenticated_principal_id()
        assert exc.value.code == "whoami-unavailable"

    def test_comment_fetch_and_create_include_author_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _jira_live_client(tmp_path, monkeypatch)

        def fake_http(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
            if method == "POST" and "/comment" in url:
                return _jira_comment(comment_id="c-created", body="hello", account_id="jira-brokered-1")
            if "/comment" in url and "startAt" in url:
                return {
                    "comments": [_jira_comment(comment_id="c1", body="fetched", account_id="user-jira-9")],
                    "maxResults": 50,
                    "total": 1,
                    "startAt": 0,
                }
            return _jira_issue_payload()

        monkeypatch.setattr(client, "_http_json", fake_http)
        record = client.get("DEMO-9")
        assert record.comments[0].author_id == "user-jira-9"
        created = client.add_comment("DEMO-9", "hello", author_id="jira-brokered-1")
        assert created.author_id == "jira-brokered-1"

    def test_create_author_mismatch_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _jira_live_client(tmp_path, monkeypatch)

        def fake_http(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
            return _jira_comment(comment_id="c-created", body="hello", account_id="other-user")

        monkeypatch.setattr(client, "_http_json", fake_http)
        with pytest.raises(IssueCommentAuthorshipMismatch):
            client.add_comment("DEMO-9", "hello", author_id="jira-brokered-1")

    def test_comments_complete_false_when_more_pages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _jira_live_client(tmp_path, monkeypatch)
        monkeypatch.setattr(pjc, "MAX_COMMENT_PAGES", 1)

        def fake_http(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
            if "/comment" in url:
                return {
                    "comments": [_jira_comment(comment_id="c1", body="page-1", account_id="u1")],
                    "maxResults": 1,
                    "total": 2,
                    "startAt": 0,
                }
            return _jira_issue_payload()

        monkeypatch.setattr(client, "_http_json", fake_http)
        record = client.get("DEMO-9")
        assert record.comments_complete is False

    def test_paginated_comments_walk_until_complete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _jira_live_client(tmp_path, monkeypatch)
        starts: list[str] = []

        def fake_http(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None) -> Any:
            if "/comment" in url:
                starts.append(url)
                if "startAt=0" in url or "startAt=0&" in url or url.endswith("startAt=0"):
                    return {
                        "comments": [_jira_comment(comment_id="c1", body="p1", account_id="u1")],
                        "maxResults": 1,
                        "total": 2,
                        "startAt": 0,
                    }
                return {
                    "comments": [_jira_comment(comment_id="c2", body="p2", account_id="u2")],
                    "maxResults": 1,
                    "total": 2,
                    "startAt": 1,
                }
            return _jira_issue_payload()

        monkeypatch.setattr(client, "_http_json", fake_http)
        record = client.get("DEMO-9")
        assert [c.id for c in record.comments] == ["c1", "c2"]
        assert record.comments_complete is True
        assert any("startAt=0" in url for url in starts)
        assert any("startAt=1" in url for url in starts)

    def test_missing_floor_keeps_provider_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pjc, "jira_r15_floor_present", lambda: False)
        caps = pjc.jira_doc_review_capabilities()
        for name in DOC_REVIEW_MANDATORY_CAPABILITIES:
            assert caps[name] is False
        monkeypatch.setattr(
            pjc,
            "jira_doc_review_capabilities",
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
        missing = missing_doc_review_capabilities("jira")
        assert missing
        out = provider_unsupported(provider="jira")
        assert out["error"] == DOC_REVIEW_PROVIDER_UNSUPPORTED


class TestNotionR15Floor:
    def test_whoami_uses_users_me_id_not_payload_claimed_author(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _notion_live_client(tmp_path)
        paths: list[str] = []

        def fake_request(
            root: Path,
            cfg: dict[str, Any],
            method: str,
            path: str,
            **kwargs: Any,
        ) -> tuple[int, dict[str, str], str]:
            paths.append(path)
            assert path == "/users/me"
            return 200, {}, json.dumps({"id": "notion-brokered-1", "object": "user", "type": "bot"})

        monkeypatch.setattr(pnc, "notion_request", fake_request)
        assert client.authenticated_principal_id() == "notion-brokered-1"
        assert "/users/me" in paths

    def test_whoami_refuses_empty_user(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _notion_live_client(tmp_path)

        def fake_request(
            root: Path,
            cfg: dict[str, Any],
            method: str,
            path: str,
            **kwargs: Any,
        ) -> tuple[int, dict[str, str], str]:
            return 200, {}, json.dumps({"id": "", "object": "user"})

        monkeypatch.setattr(pnc, "notion_request", fake_request)
        with pytest.raises(pnc.NotionClientError) as exc:
            client.authenticated_principal_id()
        assert exc.value.code == "whoami-unavailable"

    def test_comment_fetch_and_create_include_author_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _notion_live_client(tmp_path)

        def fake_request(
            root: Path,
            cfg: dict[str, Any],
            method: str,
            path: str,
            **kwargs: Any,
        ) -> tuple[int, dict[str, str], str]:
            if method == "POST" and path == "/comments":
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "id": "c-created",
                            "rich_text": [{"type": "text", "text": {"content": "hello"}}],
                            "created_time": "2026-01-01T00:00:00.000Z",
                            "created_by": {"object": "user", "id": "notion-brokered-1"},
                        }
                    ),
                )
            if path.startswith("/comments?"):
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "results": [
                                {
                                    "id": "c1",
                                    "rich_text": [{"type": "text", "text": {"content": "fetched"}}],
                                    "created_time": "2026-01-01T00:00:00.000Z",
                                    "created_by": {"object": "user", "id": "user-notion-9"},
                                }
                            ],
                            "has_more": False,
                            "next_cursor": None,
                        }
                    ),
                )
            if path.startswith("/pages/"):
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "id": "page-1",
                            "last_edited_time": "2026-01-01T00:00:00.000Z",
                            "properties": {
                                "Name": {"title": [{"type": "text", "text": {"content": "PRD"}}]},
                                "Status": {"status": {"name": "In progress"}},
                            },
                        }
                    ),
                )
            if "/blocks/" in path and "/children" in path:
                return 200, {}, json.dumps({"results": [], "has_more": False})
            raise AssertionError(f"unexpected {method} {path}")

        monkeypatch.setattr(pnc, "notion_request", fake_request)
        record = client.get("page-1")
        assert record.comments[0].author_id == "user-notion-9"
        created = client.add_comment("page-1", "hello", author_id="notion-brokered-1")
        assert created.author_id == "notion-brokered-1"

    def test_create_author_mismatch_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _notion_live_client(tmp_path)

        def fake_request(
            root: Path,
            cfg: dict[str, Any],
            method: str,
            path: str,
            **kwargs: Any,
        ) -> tuple[int, dict[str, str], str]:
            return (
                200,
                {},
                json.dumps(
                    {
                        "id": "c-created",
                        "rich_text": [{"type": "text", "text": {"content": "hello"}}],
                        "created_time": "2026-01-01T00:00:00.000Z",
                        "created_by": {"object": "user", "id": "other-user"},
                    }
                ),
            )

        monkeypatch.setattr(pnc, "notion_request", fake_request)
        with pytest.raises(IssueCommentAuthorshipMismatch):
            client.add_comment("page-1", "hello", author_id="notion-brokered-1")

    def test_comments_complete_false_when_has_more(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _notion_live_client(tmp_path)
        monkeypatch.setattr(pnc, "MAX_COMMENT_PAGES", 1)

        def fake_request(
            root: Path,
            cfg: dict[str, Any],
            method: str,
            path: str,
            **kwargs: Any,
        ) -> tuple[int, dict[str, str], str]:
            if path.startswith("/comments?"):
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "results": [
                                {
                                    "id": "c1",
                                    "rich_text": [{"type": "text", "text": {"content": "page-1"}}],
                                    "created_time": "2026-01-01T00:00:00.000Z",
                                    "created_by": {"object": "user", "id": "u1"},
                                }
                            ],
                            "has_more": True,
                            "next_cursor": "cursor_1",
                        }
                    ),
                )
            if path.startswith("/pages/"):
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "id": "page-1",
                            "last_edited_time": "2026-01-01T00:00:00.000Z",
                            "properties": {
                                "Name": {"title": [{"type": "text", "text": {"content": "PRD"}}]},
                                "Status": {"status": {"name": "In progress"}},
                            },
                        }
                    ),
                )
            if "/blocks/" in path:
                return 200, {}, json.dumps({"results": [], "has_more": False})
            raise AssertionError(f"unexpected {method} {path}")

        monkeypatch.setattr(pnc, "notion_request", fake_request)
        record = client.get("page-1")
        assert record.comments_complete is False

    def test_paginated_comments_walk_until_complete(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = _notion_live_client(tmp_path)
        paths: list[str] = []

        def fake_request(
            root: Path,
            cfg: dict[str, Any],
            method: str,
            path: str,
            **kwargs: Any,
        ) -> tuple[int, dict[str, str], str]:
            paths.append(path)
            if path.startswith("/comments?"):
                if "start_cursor=" in path:
                    return (
                        200,
                        {},
                        json.dumps(
                            {
                                "results": [
                                    {
                                        "id": "c2",
                                        "rich_text": [{"type": "text", "text": {"content": "p2"}}],
                                        "created_time": "2026-01-01T00:00:01.000Z",
                                        "created_by": {"object": "user", "id": "u2"},
                                    }
                                ],
                                "has_more": False,
                                "next_cursor": None,
                            }
                        ),
                    )
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "results": [
                                {
                                    "id": "c1",
                                    "rich_text": [{"type": "text", "text": {"content": "p1"}}],
                                    "created_time": "2026-01-01T00:00:00.000Z",
                                    "created_by": {"object": "user", "id": "u1"},
                                }
                            ],
                            "has_more": True,
                            "next_cursor": "cursor_1",
                        }
                    ),
                )
            if path.startswith("/pages/"):
                return (
                    200,
                    {},
                    json.dumps(
                        {
                            "id": "page-1",
                            "last_edited_time": "2026-01-01T00:00:00.000Z",
                            "properties": {
                                "Name": {"title": [{"type": "text", "text": {"content": "PRD"}}]},
                                "Status": {"status": {"name": "In progress"}},
                            },
                        }
                    ),
                )
            if "/blocks/" in path:
                return 200, {}, json.dumps({"results": [], "has_more": False})
            raise AssertionError(f"unexpected {method} {path}")

        monkeypatch.setattr(pnc, "notion_request", fake_request)
        record = client.get("page-1")
        assert [c.id for c in record.comments] == ["c1", "c2"]
        assert record.comments_complete is True
        assert any("start_cursor=cursor_1" in path for path in paths)

    def test_missing_floor_keeps_provider_unsupported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(pnc, "notion_r15_floor_present", lambda: False)
        caps = pnc.notion_doc_review_capabilities()
        for name in DOC_REVIEW_MANDATORY_CAPABILITIES:
            assert caps[name] is False


class TestJiraNotionR6Enablement:
    def test_jira_and_notion_advertise_mandatory_capabilities_after_floor(self) -> None:
        assert pjc.jira_r15_floor_present() is True
        assert pnc.notion_r15_floor_present() is True
        for provider in ("jira", "notion"):
            caps = doc_review_capabilities_for(provider)
            assert missing_doc_review_capabilities(provider) == []
            for name in DOC_REVIEW_MANDATORY_CAPABILITIES:
                assert caps[name] is True, (provider, name)
            assert provider in DOC_REVIEW_ENABLED_PROVIDERS
        assert "linear" in DOC_REVIEW_ENABLED_PROVIDERS
        assert "github-issues" in DOC_REVIEW_ENABLED_PROVIDERS

    def test_unshipped_providers_stay_unsupported(self) -> None:
        for provider in ("gitlab-issues", "none"):
            assert provider not in DOC_REVIEW_ENABLED_PROVIDERS
            assert missing_doc_review_capabilities(provider)

    def test_jira_findings_size_cap_is_cloud_comment_limit(self) -> None:
        from planning_doc_review_transport import DOC_REVIEW_COMMENT_SIZE_CAP

        assert JIRA_CLOUD_DESCRIPTION_LIMIT < DOC_REVIEW_COMMENT_SIZE_CAP
        # post_review_finding should refuse Jira payloads above the Cloud ADF comment cap.
        from planning_doc_review_transport import post_review_finding_size_limit_for

        assert post_review_finding_size_limit_for("jira") == JIRA_CLOUD_DESCRIPTION_LIMIT
        assert post_review_finding_size_limit_for("notion") <= DOC_REVIEW_COMMENT_SIZE_CAP

    def test_closed_set_is_github_linear_jira_notion(self) -> None:
        assert DOC_REVIEW_ENABLED_PROVIDERS == frozenset(
            {"github-issues", "linear", "jira", "notion"}
        )


class TestTr5MarkerEncoding:
    def test_adf_persists_same_marker_family_as_paragraph_not_html_comment_node(self) -> None:
        body = build_doc_review_comment_body(
            round_id="r-adf",
            persona="coherence",
            payload=_sample_findings(),
        )
        adf = pjc.encode_doc_review_marker_family_for_adf(body)
        types = {node.get("type") for node in adf.get("content") or []}
        assert "comment" not in types
        assert "paragraph" in types
        texts: list[str] = []
        for node in adf.get("content") or []:
            for child in node.get("content") or []:
                if isinstance(child, dict) and child.get("text"):
                    texts.append(str(child["text"]))
        joined = "\n".join(texts)
        assert "<!-- sw-doc-review -->" in joined
        assert "sw-doc-review-adf" not in joined
        back = adf_to_markdown(adf)
        assert parse_doc_review_comment(back) is not None

    def test_notion_discussion_persists_same_marker_family(self) -> None:
        body = build_doc_review_comment_body(
            round_id="r-notion",
            persona="coherence",
            payload=_sample_findings(),
        )
        rich = pnc.encode_doc_review_marker_family_for_discussion(body)
        text = "".join(
            str((item.get("text") or {}).get("content") or "")
            for item in rich
            if isinstance(item, dict)
        )
        assert "<!-- sw-doc-review -->" in text
        assert "sw-doc-review-notion" not in text
        assert parse_doc_review_comment(text) is not None

    def test_round_witness_survives_adf_and_notion_encoding(self) -> None:
        prefix = "<!-- sw-unit-id: u -->\n# PRD\n\nBody.\n"
        block = {"roundId": "r-tr5", "status": "open", "unitId": "u", "issueId": "1", "pins": []}
        full = upsert_review_round_block(prefix, block)
        adf_back = adf_to_markdown(pjc.encode_doc_review_marker_family_for_adf(full))
        parsed, err = inspect_review_round_block(adf_back)
        assert err is None, err
        assert parsed["roundId"] == "r-tr5"
        rich = pnc.encode_doc_review_marker_family_for_discussion(full)
        discussion = "".join(
            str((item.get("text") or {}).get("content") or "")
            for item in rich
            if isinstance(item, dict)
        )
        parsed_n, err_n = inspect_review_round_block(discussion)
        assert err_n is None, err_n
        assert parsed_n["roundId"] == "r-tr5"
