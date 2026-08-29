"""PRD 341 phase 7 — complete_review_round closes + appends completion receipt (R22/R23/D21)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from issues_lib import get_fixture_store
from planning_doc_review_transport import (
    DOC_REVIEW_COMPLETION_API_VERSION,
    DOC_REVIEW_COMPLETION_MARKER,
    body_manifest_id,
    build_completion_receipt_body,
    default_completion_idempotency_key,
    find_completion_receipts,
    inspect_review_round_block,
    parse_completion_receipt,
)
from planning_store_facade import complete_review_round, load_workflow_config
from unit_tests.planning.test_doc_review_transport_bootstrap import (
    _fixture_bot,
    _init_repo,
    _issue_store_cfg,
    _post_then_open,
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


def test_build_and_parse_completion_receipt() -> None:
    body = build_completion_receipt_body(
        unit_id="unit-341",
        round_id="r1",
        manifest_id="body-manifest:1:r1",
        manifest_revision_token="etag-1",
        idempotency_key_value="r1:completion:body-manifest:1:r1",
        completed_at="2026-08-29T00:00:00Z",
        body_path="docs/prds/341/prd.md",
    )
    assert DOC_REVIEW_COMPLETION_MARKER in body
    parsed = parse_completion_receipt(body)
    assert parsed is not None
    assert parsed["apiVersion"] == DOC_REVIEW_COMPLETION_API_VERSION
    assert parsed["verification"] == "verified"
    assert parsed["manifestId"] == "body-manifest:1:r1"


def test_complete_sets_closed_and_appends_one_receipt(transport_repo: Path) -> None:
    cfg = load_workflow_config(transport_repo)
    store = get_fixture_store(transport_repo)
    unit_id = "341-prd-doc-review-transport"
    _seed_issue(store, unit_id=unit_id)
    round_id = "round-complete-1"
    opened, _ids = _post_then_open(
        transport_repo,
        cfg,
        unit_id=unit_id,
        round_id=round_id,
    )
    assert opened["verdict"] == "ok"
    pins_at_open = [dict(p) for p in (opened.get("pins") or [])]

    closed = complete_review_round(
        transport_repo,
        cfg,
        issue_id="887",
        unit_id=unit_id,
        round_id=round_id,
    )
    assert closed["verdict"] == "ok", closed
    assert closed["status"] == "closed"
    assert closed.get("idempotent") is False
    assert closed.get("receiptCommentId")
    receipt = closed["receipt"]
    assert receipt["kind"] == "DocReviewCompletion"
    assert receipt["roundId"] == round_id
    assert receipt["verification"] == "verified"
    assert receipt["apiVersion"] == DOC_REVIEW_COMPLETION_API_VERSION

    record = get_fixture_store(transport_repo).get("887")
    manifest, err = inspect_review_round_block(record.body)
    assert err is None
    assert manifest["status"] == "closed"
    # Pins unchanged (D21)
    assert [p.get("commentId") for p in (manifest.get("pins") or [])] == [
        p.get("commentId") for p in pins_at_open
    ]

    manifest_id = body_manifest_id(issue_id="887", round_id=round_id)
    key = default_completion_idempotency_key(round_id=round_id, manifest_id=manifest_id)
    matches = find_completion_receipts(list(record.comments), round_id=round_id, idempotency_key_value=key)
    assert len(matches) == 1


def test_completion_replay_returns_same_receipt(transport_repo: Path) -> None:
    cfg = load_workflow_config(transport_repo)
    store = get_fixture_store(transport_repo)
    unit_id = "341-prd-doc-review-transport"
    _seed_issue(store, unit_id=unit_id)
    round_id = "round-complete-replay"
    _post_then_open(transport_repo, cfg, unit_id=unit_id, round_id=round_id)

    first = complete_review_round(
        transport_repo,
        cfg,
        issue_id="887",
        unit_id=unit_id,
        round_id=round_id,
    )
    assert first["verdict"] == "ok", first
    second = complete_review_round(
        transport_repo,
        cfg,
        issue_id="887",
        unit_id=unit_id,
        round_id=round_id,
    )
    assert second["verdict"] == "ok", second
    assert second.get("idempotent") is True
    assert second["receiptCommentId"] == first["receiptCommentId"]
    assert second["receipt"]["idempotencyKey"] == first["receipt"]["idempotencyKey"]
    assert second["receipt"]["manifestId"] == first["receipt"]["manifestId"]

    record = get_fixture_store(transport_repo).get("887")
    manifest_id = body_manifest_id(issue_id="887", round_id=round_id)
    key = default_completion_idempotency_key(round_id=round_id, manifest_id=manifest_id)
    matches = find_completion_receipts(list(record.comments), round_id=round_id, idempotency_key_value=key)
    assert len(matches) == 1
