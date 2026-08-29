"""PRD 341 phase 8 — freeze-hash exclusion + inbound/deliver channel isolation (R24–R26/R31/D22)."""

from __future__ import annotations

from planning_canonical import (
    CommentRecord,
    IssueSnapshot,
    build_freeze_record_body,
    canonical_hash,
    inbound_authoring_comments,
    is_inbound_authoring_comment,
    strip_doc_review_witness_for_hash,
)
from planning_doc_review_transport import (
    build_completion_receipt_body,
    build_doc_review_comment_body,
    render_review_round_block,
)


def _base_snap(*, body: str, comments: list[CommentRecord] | None = None) -> IssueSnapshot:
    return IssueSnapshot(
        title="PRD",
        body=body,
        state="open",
        labels=["sw:prd"],
        comments=list(comments or []),
    )


def test_findings_and_completion_do_not_change_canonical_hash() -> None:
    base_body = "<!-- sw-unit-id: u -->\n# Body\n"
    base = _base_snap(body=base_body)
    base_hash = canonical_hash(base)

    findings = CommentRecord(
        id="c-find",
        body=build_doc_review_comment_body(
            round_id="r1",
            persona="coherence",
            payload={"reviewer": "coherence", "findings": []},
        ),
        created_at="1",
        markers=["sw-doc-review"],
    )
    receipt = CommentRecord(
        id="c-receipt",
        body=build_completion_receipt_body(
            unit_id="u",
            round_id="r1",
            manifest_id="body-manifest:1:r1",
            manifest_revision_token="etag",
            idempotency_key_value="r1:completion:body-manifest:1:r1",
            completed_at="2026-08-29T00:00:00Z",
        ),
        created_at="2",
        markers=["sw:doc-review-completion"],
    )
    with_system = _base_snap(body=base_body, comments=[findings, receipt])
    assert canonical_hash(with_system) == base_hash


def test_body_witness_excluded_from_hash_but_remains_live() -> None:
    bare = "<!-- sw-unit-id: u -->\n# Body\n"
    witness = render_review_round_block(
        {
            "apiVersion": "shipwright.dev/doc-review-manifest/v1",
            "kind": "DocReviewManifest",
            "roundId": "r1",
            "status": "open",
            "pins": [],
        }
    )
    live = f"{bare}\n{witness}\n"
    assert "sw-doc-review-round" in live or "doc-review-round" in live
    assert "doc-review-round" not in strip_doc_review_witness_for_hash(live)

    bare_hash = canonical_hash(_base_snap(body=bare))
    live_hash = canonical_hash(_base_snap(body=live))
    assert live_hash == bare_hash
    # Live body unchanged by hashing helpers
    assert "doc-review-round" in live


def test_marked_records_excluded_from_inbound_channel() -> None:
    human = CommentRecord(id="h1", body="Operator note", created_at="1", markers=[])
    findings = CommentRecord(
        id="f1",
        body=build_doc_review_comment_body(
            round_id="r1",
            persona="security",
            payload={"reviewer": "security", "findings": []},
        ),
        created_at="2",
        markers=["sw:doc-review"],
    )
    receipt = CommentRecord(
        id="r1",
        body=build_completion_receipt_body(
            unit_id="u",
            round_id="r1",
            manifest_id="m",
            manifest_revision_token="t",
            idempotency_key_value="k",
        ),
        created_at="3",
        markers=["sw:doc-review-completion"],
    )
    assert is_inbound_authoring_comment(human) is True
    assert is_inbound_authoring_comment(findings) is False
    assert is_inbound_authoring_comment(receipt) is False
    inbound = inbound_authoring_comments([human, findings, receipt])
    assert [c.id for c in inbound] == ["h1"]


def test_freeze_record_still_excluded() -> None:
    body = "<!-- sw-unit-id: u -->\n# Body\n"
    freeze = CommentRecord(
        id="fr",
        body=build_freeze_record_body("a" * 64),
        created_at="1",
        markers=["sw-freeze-record"],
    )
    assert canonical_hash(_base_snap(body=body, comments=[freeze])) == canonical_hash(
        _base_snap(body=body)
    )
