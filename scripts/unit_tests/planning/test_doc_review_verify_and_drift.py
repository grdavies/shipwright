"""Phase 6 — verify re-read + typed comment/body drift (PRD 341 R19–R21/R32)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from issues_lib import get_fixture_store
from planning_canonical import CommentRecord
from planning_doc_review_transport import (
    DOC_REVIEW_BODY_DRIFT,
    DOC_REVIEW_COMMENT_DRIFT,
    build_doc_review_comment_body,
    stripped_artifact_hash,
)
from planning_store_facade import load_workflow_config, verify_review_manifest
from unit_tests.planning.test_doc_review_transport_bootstrap import (
    FIXTURE_GITHUB_PRINCIPAL_ID,
    _fixture_bot,
    _init_repo,
    _issue_store_cfg,
    _post_then_open,
    _sample_payload,
    _seed_issue,
)


@pytest.fixture
def transport_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    get_fixture_store(root).clear()
    _fixture_bot(monkeypatch)
    return root


def _open_round(
    root: Path,
    *,
    unit_id: str = "341-prd-doc-review-transport",
    round_id: str = "round-v",
) -> tuple[dict, list[str]]:
    cfg = load_workflow_config(root)
    store = get_fixture_store(root)
    _seed_issue(store, unit_id=unit_id)
    return _post_then_open(
        root,
        cfg,
        unit_id=unit_id,
        round_id=round_id,
        personas=[
            ("coherence", _sample_payload("coherence")),
            ("security", _sample_payload("security")),
        ],
    )


class TestVerifyReRead:
    def test_verify_ok_after_open(self, transport_repo: Path) -> None:
        opened, _ids = _open_round(transport_repo)
        assert opened["verdict"] == "ok"
        cfg = load_workflow_config(transport_repo)
        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-v",
        )
        assert out["verdict"] == "ok"
        assert out["roundId"] == "round-v"
        assert out.get("artifactHash") == opened["artifactHash"]

    def test_bad_marker_on_pinned_comment_fails_verify(self, transport_repo: Path) -> None:
        opened, comment_ids = _open_round(transport_repo)
        assert opened["verdict"] == "ok"
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        target = comment_ids[0]
        for comment in record.comments:
            if comment.id == target:
                comment.body = "not a marked doc-review comment"
                comment.markers = []
                break
        store._persist()
        cfg = load_workflow_config(transport_repo)
        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-v",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out.get("driftKind") == "malformed"


class TestCommentDrift:
    def test_added_comment_after_open_is_comment_drift(self, transport_repo: Path) -> None:
        opened, _ids = _open_round(transport_repo)
        assert opened["verdict"] == "ok"
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        extra_body = build_doc_review_comment_body(
            round_id="round-v",
            persona="product",
            payload=_sample_payload("product"),
        )
        record.comments.append(
            CommentRecord(
                id="comment-extra",
                body=extra_body,
                created_at="999",
                markers=["sw-doc-review"],
                author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
                revision="999",
            )
        )
        store._persist()
        cfg = load_workflow_config(transport_repo)
        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-v",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out.get("driftKind") == "added"

    def test_reorder_pins_is_comment_drift(self, transport_repo: Path) -> None:
        opened, comment_ids = _open_round(transport_repo)
        assert opened["verdict"] == "ok"
        assert len(comment_ids) >= 2
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        from planning_doc_review_transport import (
            parse_review_round_block,
            upsert_review_round_block,
        )

        # Swap pin order in the body witness while comments stay in open order (R20).
        manifest = parse_review_round_block(record.body)
        pins = list(manifest.get("pins") or [])
        assert len(pins) >= 2
        pins[0], pins[1] = pins[1], pins[0]
        manifest["pins"] = pins
        record.body = upsert_review_round_block(record.body, manifest)
        store._persist()
        cfg = load_workflow_config(transport_repo)
        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-v",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out.get("driftKind") == "reorder"


class TestBodyDrift:
    def test_stripped_hash_mismatch_is_body_drift(self, transport_repo: Path) -> None:
        opened, _ids = _open_round(transport_repo)
        assert opened["verdict"] == "ok"
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        mutated = record.body + "\n\noperator edit outside witness\n"
        assert stripped_artifact_hash(mutated) != opened["artifactHash"]
        record.body = mutated
        record.etag = '"etag-after-body-edit"'
        store._persist()
        cfg = load_workflow_config(transport_repo)
        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-v",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_BODY_DRIFT
        assert out.get("driftKind") == "body"

    def test_etag_only_change_does_not_body_drift(self, transport_repo: Path) -> None:
        opened, _ids = _open_round(transport_repo)
        assert opened["verdict"] == "ok"
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.etag = '"etag-only-bump"'
        store._persist()
        assert stripped_artifact_hash(record.body) == opened["artifactHash"]
        cfg = load_workflow_config(transport_repo)
        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-v",
        )
        assert out["verdict"] == "ok"
        assert out.get("error") != DOC_REVIEW_BODY_DRIFT
