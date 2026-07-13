"""PRD 066 phase 8 — threaded comments + typed relations facade (R17, R24)."""

from __future__ import annotations

import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_client as plc
import planning_store as ps
from issues_lib import IssueRecord
from planning_canonical import (
    CommentRecord,
    RelationRecord,
    build_comment_threads,
    normalize_flat_provider_comments,
    serialize_comment_facade,
)


def _threaded_comments() -> list[CommentRecord]:
    return [
        CommentRecord(
            id="cmt-root-open",
            body="Open thread root",
            created_at="2026-01-01T00:00:00Z",
        ),
        CommentRecord(
            id="cmt-root-resolved",
            body="Resolved thread root",
            created_at="2026-01-02T00:00:00Z",
            resolved_at="2026-01-03T00:00:00Z",
            resolving_comment_id="cmt-resolve-note",
        ),
        CommentRecord(
            id="cmt-reply",
            body="Reply under open root",
            created_at="2026-01-01T01:00:00Z",
            parent_id="cmt-root-open",
        ),
        CommentRecord(
            id="cmt-resolve-note",
            body="Resolution note",
            created_at="2026-01-03T00:00:00Z",
            parent_id="cmt-root-resolved",
        ),
    ]


def _bidirectional_relations(issue_id: str = "iss-1") -> list[RelationRecord]:
    return [
        RelationRecord(
            id="rel-out",
            relation_type="blocks",
            source_issue_id=issue_id,
            target_issue_id="iss-2",
            direction="outbound",
        ),
        RelationRecord(
            id="rel-in",
            relation_type="blocked",
            source_issue_id="iss-3",
            target_issue_id=issue_id,
            direction="inbound",
        ),
    ]


def test_r24_comment_record_preserves_parentage_and_resolved() -> None:
    """R24 — CommentRecord fixtures preserve parentage/resolved metadata."""
    comments = _threaded_comments()
    threads = build_comment_threads(comments)
    assert threads["roots"] == ["cmt-root-open", "cmt-root-resolved"]
    assert threads["replies"]["cmt-root-open"] == ["cmt-reply"]
    assert threads["resolvedThreadRoots"] == ["cmt-root-resolved"]
    assert threads["unresolvedThreadRoots"] == ["cmt-root-open"]

    root_open = serialize_comment_facade(comments[0])
    assert root_open["parentId"] is None
    assert root_open["threadStatus"] == "root"
    resolved = serialize_comment_facade(comments[1])
    assert resolved["resolvedAt"] == "2026-01-03T00:00:00Z"
    assert resolved["resolvingCommentId"] == "cmt-resolve-note"
    assert resolved["threadStatus"] == "resolved"


def test_r24_flat_provider_paths_non_regress() -> None:
    """R24 — GitHub/Jira flat paths do not invent thread metadata."""
    flat = [
        CommentRecord(id="1", body="flat comment", created_at="t1"),
        CommentRecord(id="2", body="another", created_at="t2"),
    ]
    normalized = normalize_flat_provider_comments(flat)
    assert all(comment.parent_id == "" for comment in normalized)
    assert all(comment.resolved_at == "" for comment in normalized)

    payload = ps.serialize_comments_relations_facade(
        flat,
        [],
        provider="github-issues",
    )
    assert payload["flatCommentPath"] is True
    assert payload["comments"][0]["parentId"] is None
    assert ps.assert_flat_comment_provider_non_regression("github-issues", normalized)["verdict"] == "pass"

    polluted = [
        CommentRecord(id="x", body="bad", parent_id="y"),
    ]
    assert (
        ps.assert_flat_comment_provider_non_regression("jira", polluted)["verdict"] == "fail"
    )


def test_r24_facade_schema_contract_and_issue_facade() -> None:
    """R24 — planning_store exposes normative facade schema + issue read helper."""
    contract = ps.comments_relations_schema_contract()
    assert contract["verdict"] == "ok"
    assert "parentId" in contract["commentFields"]
    assert "resolvedAt" in contract["commentFields"]
    assert "direction" in contract["relationFields"]
    assert contract["gap077AuthoringAccepted"] is False

    record = IssueRecord(
        id="iss-1",
        number=1,
        title="Gap",
        body="# Gap",
        state="open",
        labels=["sw:gap"],
        comments=_threaded_comments(),
        relations=_bidirectional_relations(),
        project_key="fixture-066",
        artifact_type="gap",
        unit_id="gap-079",
    )
    facade = ps.issue_comments_relations_facade(record, provider="linear")
    assert facade["verdict"] == "ok"
    assert facade["issueId"] == "iss-1"
    assert len(facade["comments"]) == 4
    assert len(facade["relations"]) == 2
    assert facade["gap077AuthoringAccepted"] is False

    op_contract = ps.operator_projection_contract()
    assert "commentsRelations" in op_contract
    assert op_contract["commentsRelations"]["gap077AuthoringAccepted"] is False


def test_r17_linear_surface_threads_and_bidirectional_relations() -> None:
    """R17 — Linear provider surface exposes threads + inbound/outbound relations."""
    payload = {
        "id": "iss-1",
        "identifier": "LIN-1",
        "description": "# Gap",
        "labels": {"nodes": [{"name": "sw:gap"}]},
        "comments": {
            "nodes": [
                {
                    "id": "cmt-root-open",
                    "body": "Open thread root",
                    "createdAt": "2026-01-01T00:00:00Z",
                },
                {
                    "id": "cmt-reply",
                    "body": "Reply",
                    "createdAt": "2026-01-01T01:00:00Z",
                    "parent": {"id": "cmt-root-open"},
                },
                {
                    "id": "cmt-root-resolved",
                    "body": "Resolved",
                    "createdAt": "2026-01-02T00:00:00Z",
                    "resolvedAt": "2026-01-03T00:00:00Z",
                    "resolvingComment": {"id": "cmt-resolve-note"},
                },
            ]
        },
        "relations": {
            "nodes": [
                {
                    "id": "rel-out",
                    "type": "blocks",
                    "relatedIssue": {"id": "iss-2", "identifier": "LIN-2"},
                }
            ]
        },
        "inverseRelations": {
            "nodes": [
                {
                    "id": "rel-in",
                    "type": "blocked",
                    "issue": {"id": "iss-3", "identifier": "LIN-3"},
                }
            ]
        },
    }
    surface = plc.linear_comments_relations_surface(payload, project_key="fixture-066")
    assert surface["verdict"] == "ok"
    assert surface["provider"] == "linear"
    assert surface["threads"]["unresolvedThreadRoots"] == ["cmt-root-open"]
    assert surface["threads"]["resolvedThreadRoots"] == ["cmt-root-resolved"]
    assert {row["direction"] for row in surface["relations"]} == {"outbound", "inbound"}
    assert surface["gap077AuthoringAccepted"] is False

    record = plc._record_from_issue(payload, project_key="fixture-066")
    assert len(record.comments) == 3
    assert record.comments[1].parent_id == "cmt-root-open"
    assert record.comments[2].resolved_at == "2026-01-03T00:00:00Z"
    assert len(record.relations) == 2
