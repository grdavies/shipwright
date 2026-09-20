"""PRD 365 phase 4 — body-drift fixtures and finding-text non-persistence (R7, R8, R10)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from issues_lib import IssuesClient, get_fixture_store
from planning_doc_review_transport import (
    DOC_REVIEW_APPLY_WITNESS_STRIPPED,
    DOC_REVIEW_BODY_DRIFT,
    apply_closed_round_stripped_body,
    body_manifest_id,
    default_completion_idempotency_key,
    find_completion_receipts,
    inspect_review_round_block,
    logical_issue_body,
    normalize_finding_envelope,
    parse_doc_review_comment,
    render_review_round_block,
    strip_review_round_blocks,
    witness_block_text,
)
from planning_store_facade import (
    complete_review_round,
    load_workflow_config,
    verify_review_manifest,
)
from unit_tests.planning.test_doc_review_transport_bootstrap import (
    _fixture_bot,
    _init_repo,
    _issue_store_cfg,
    _post_then_open,
    _sample_payload,
    _seed_issue,
)

_SECRET_TITLE = "PRD365-SECRET-TITLE-MARKER"
_SECRET_WHY = "PRD365-SECRET-WHY-IT-MATTERS"
_SECRET_EVIDENCE = "PRD365-SECRET-EVIDENCE-SNIPPET"
_SECRET_FIX = "PRD365-SECRET-SUGGESTED-FIX"

_FORBIDDEN_FINDING_KEYS = frozenset(
    {
        "title",
        "why-it-matters",
        "why_it_matters",
        "evidence",
        "suggested-fix",
        "suggested_fix",
    }
)


def _payload_with_secret_markers(persona: str = "coherence") -> dict[str, Any]:
    base = _sample_payload(persona)
    finding = dict(base["findings"][0])
    finding["title"] = _SECRET_TITLE
    finding["why_it_matters"] = _SECRET_WHY
    finding["evidence"] = [_SECRET_EVIDENCE]
    finding["suggested_fix"] = _SECRET_FIX
    base["findings"] = [finding]
    return base


def _assert_no_finding_text_in_blob(blob: str) -> None:
    for marker in (_SECRET_TITLE, _SECRET_WHY, _SECRET_EVIDENCE, _SECRET_FIX):
        assert marker not in blob
    lowered = blob.lower()
    for key in _FORBIDDEN_FINDING_KEYS:
        assert f'"{key}"' not in lowered


def _assert_no_finding_text_in_obj(obj: Any) -> None:
    _assert_no_finding_text_in_blob(json.dumps(obj, sort_keys=True))


def _mutate_stripped_body_before_complete(
    repo: Path,
    *,
    issue_id: str = "887",
) -> None:
    """Simulate operator body edit on the live fixture store (pre-complete)."""
    client = IssuesClient(repo, "github-issues")
    record = client.issue_get(issue_id)
    client.issue_update(
        issue_id,
        body=(record.body or "") + "\n\noperator edit outside witness\n",
        if_match=record.etag,
    )


@pytest.fixture
def transport_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ("." + "cursor") / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    get_fixture_store(root).clear()
    _fixture_bot(monkeypatch)
    return root


class TestMutateBeforeCompleteBodyDrift:
    def test_complete_refuses_when_stripped_body_mutated_before_close(
        self, transport_repo: Path
    ) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "365-doc-review-synth-order"
        round_id = "round-mutate-before-complete"
        _seed_issue(store, unit_id=unit_id)
        _post_then_open(
            transport_repo,
            cfg,
            unit_id=unit_id,
            round_id=round_id,
            personas=[("coherence", _payload_with_secret_markers())],
        )

        _mutate_stripped_body_before_complete(transport_repo)

        closed = complete_review_round(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
        )
        assert closed["verdict"] == "fail"
        assert closed["error"] == DOC_REVIEW_BODY_DRIFT
        assert closed.get("driftKind") == "body"
        _assert_no_finding_text_in_obj(closed)


class TestCompleteThenApplyWitnessPreserving:
    def test_complete_on_unchanged_then_fresh_read_apply_passes(
        self, transport_repo: Path
    ) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "365-doc-review-synth-order"
        round_id = "round-complete-then-apply"
        _seed_issue(store, unit_id=unit_id)
        _post_then_open(
            transport_repo,
            cfg,
            unit_id=unit_id,
            round_id=round_id,
            personas=[("coherence", _payload_with_secret_markers())],
        )

        closed = complete_review_round(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
        )
        assert closed["verdict"] == "ok", closed
        _assert_no_finding_text_in_obj(closed)
        _assert_no_finding_text_in_obj(closed.get("receipt") or {})

        client = IssuesClient(transport_repo, "github-issues")
        fresh = client.issue_get("887")
        logical_before = logical_issue_body(fresh)
        witness_before = witness_block_text(logical_before)
        assert witness_before

        finding_comment = next(
            c for c in fresh.comments if parse_doc_review_comment(c.body or "") is not None
        )
        envelope = normalize_finding_envelope(parse_doc_review_comment(finding_comment.body) or {})

        stripped_only = strip_review_round_blocks(logical_before).rstrip() + "\n\n## Applied after close\n"
        applied = apply_closed_round_stripped_body(
            client,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
            stripped_body=stripped_only,
            apply_envelopes=[envelope],
        )
        assert applied["verdict"] == "ok", applied

        after = client.issue_get("887")
        logical_after = logical_issue_body(after)
        assert witness_block_text(logical_after) == witness_before
        assert "## Applied after close" in logical_after

    def test_apply_that_strips_witness_fails(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "365-doc-review-synth-order"
        round_id = "round-apply-strips-witness"
        _seed_issue(store, unit_id=unit_id)
        _post_then_open(
            transport_repo,
            cfg,
            unit_id=unit_id,
            round_id=round_id,
            personas=[("coherence", _payload_with_secret_markers())],
        )
        closed = complete_review_round(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
        )
        assert closed["verdict"] == "ok", closed

        client = IssuesClient(transport_repo, "github-issues")
        record = client.issue_get("887")
        logical = logical_issue_body(record)
        manifest, _ = inspect_review_round_block(record.body)
        assert manifest is not None
        witness_in_stripped = strip_review_round_blocks(logical) + render_review_round_block(manifest)

        finding_comment = next(
            c for c in record.comments if parse_doc_review_comment(c.body or "") is not None
        )
        envelope = normalize_finding_envelope(parse_doc_review_comment(finding_comment.body) or {})

        applied = apply_closed_round_stripped_body(
            client,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
            stripped_body=witness_in_stripped,
            apply_envelopes=[envelope],
        )
        assert applied["verdict"] == "fail"
        assert applied["error"] == DOC_REVIEW_APPLY_WITNESS_STRIPPED
        _assert_no_finding_text_in_obj(applied)


class TestReceiptsOmitFindingText:
    def test_verify_body_drift_output_omits_finding_text(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "365-doc-review-synth-order"
        round_id = "round-body-drift-output"
        _seed_issue(store, unit_id=unit_id)
        opened, _ = _post_then_open(
            transport_repo,
            cfg,
            unit_id=unit_id,
            round_id=round_id,
            personas=[("coherence", _payload_with_secret_markers())],
        )
        assert opened["verdict"] == "ok"

        _mutate_stripped_body_before_complete(transport_repo)

        out = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_BODY_DRIFT
        _assert_no_finding_text_in_obj(out)

    def test_completion_receipt_comment_body_omits_finding_text(
        self, transport_repo: Path
    ) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "365-doc-review-synth-order"
        round_id = "round-receipt-no-finding-text"
        _seed_issue(store, unit_id=unit_id)
        _post_then_open(
            transport_repo,
            cfg,
            unit_id=unit_id,
            round_id=round_id,
            personas=[("coherence", _payload_with_secret_markers())],
        )
        closed = complete_review_round(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
        )
        assert closed["verdict"] == "ok", closed

        record = IssuesClient(transport_repo, "github-issues").issue_get("887")
        manifest_id = body_manifest_id(issue_id="887", round_id=round_id)
        key = default_completion_idempotency_key(round_id=round_id, manifest_id=manifest_id)
        matches = find_completion_receipts(list(record.comments), round_id=round_id, idempotency_key_value=key)
        assert len(matches) == 1
        receipt_comment, _envelope = matches[0]
        _assert_no_finding_text_in_blob(receipt_comment.body or "")
        _assert_no_finding_text_in_obj(closed.get("receipt") or {})
