"""Phase 10 — bootstrap compatibility and round identity (PRD 341 R35/R37/R43/D23)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from issues_lib import FIXTURE_GITHUB_PRINCIPAL_ID, get_fixture_store
from planning_canonical import CommentRecord
from planning_doc_review_transport import (
    BODY_SHA256_V1_PREFIX,
    DOC_REVIEW_FINDINGS_API_VERSION,
    DOC_REVIEW_MIXED_SCHEMA,
    build_bootstrap_finding_comment_body,
    build_doc_review_comment_body,
    envelope_immutable_equal,
    is_bootstrap_manifest,
    is_v1_finding_envelope,
    normalize_finding_envelope,
    parse_doc_review_comment,
    parse_review_round_block,
    pin_revision_matches,
    upsert_review_round_block,
    validate_doc_review_envelope,
)
from planning_store_facade import (
    complete_review_round,
    load_workflow_config,
    open_review_manifest,
    post_review_finding,
    verify_review_manifest,
)
from unit_tests.planning.test_doc_review_transport_bootstrap import (
    _fixture_bot,
    _init_repo,
    _issue_store_cfg,
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


class TestFindingEnvelopeDualRead:
    def test_new_posts_emit_api_version_envelope(self) -> None:
        body = build_doc_review_comment_body(
            round_id="r1",
            persona="coherence",
            payload=_sample_payload("coherence"),
            unit_id="341-prd-x",
        )
        parsed = parse_doc_review_comment(body)
        assert parsed is not None
        assert is_v1_finding_envelope(parsed)
        assert parsed["apiVersion"] == DOC_REVIEW_FINDINGS_API_VERSION
        assert validate_doc_review_envelope(parsed) is None

    def test_shipped_bootstrap_envelope_accepted(self) -> None:
        body = build_bootstrap_finding_comment_body(
            round_id="r1",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        parsed = parse_doc_review_comment(body)
        assert parsed is not None
        assert not is_v1_finding_envelope(parsed)
        assert {"round", "persona", "payload"} <= set(parsed)
        assert validate_doc_review_envelope(parsed) is None
        # Minimal shipped shape without derived key/hash still validates after normalize.
        minimal = {"round": "r1", "persona": "coherence", "payload": _sample_payload("coherence")}
        assert validate_doc_review_envelope(minimal) is None

    def test_bootstrap_and_v1_envelope_immutable_equal(self) -> None:
        payload = _sample_payload("coherence")
        bootstrap = {
            "round": "r1",
            "persona": "coherence",
            "payload": payload,
        }
        v1 = {
            "apiVersion": DOC_REVIEW_FINDINGS_API_VERSION,
            "kind": "DocReviewFinding",
            "roundId": "r1",
            "personaId": "coherence",
            "findings": payload,
            "idempotencyKey": "r1:coherence",
        }
        assert envelope_immutable_equal(bootstrap, v1)
        assert normalize_finding_envelope(v1)["round"] == "r1"


class TestBootstrapInFlightRound:
    def test_open_then_post_close_accepts_updated_at_pins(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)

        # Seed an open bootstrap (pre-apiVersion) body witness — open-then-post path.
        record = store.get("887")
        bootstrap_manifest = {
            "roundId": "round-bootstrap",
            "status": "open",
            "unitId": unit_id,
            "issueId": "887",
            "pins": [],
            "artifactRevision": record.etag,
        }
        record.body = upsert_review_round_block(record.body, bootstrap_manifest)
        record.touch()
        store._persist()  # noqa: SLF001 — fixture store
        assert is_bootstrap_manifest(parse_review_round_block(store.get("887").body))

        posted = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bootstrap",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        assert not str(posted["revision"]).startswith(BODY_SHA256_V1_PREFIX)

        # Fixture store instances are load-from-disk; re-read after client writes.
        refreshed = get_fixture_store(transport_repo).get("887")
        manifest = parse_review_round_block(refreshed.body)
        assert is_bootstrap_manifest(manifest)
        assert len(manifest.get("pins") or []) == 1
        pin_rev = str((manifest["pins"][0]).get("revision") or "")
        comment = refreshed.comments[0]
        assert pin_rev == str(comment.revision or "")
        assert pin_revision_matches(pin_rev, comment, bootstrap=True)

        verified = verify_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bootstrap",
        )
        assert verified["verdict"] == "ok"

        closed = complete_review_round(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bootstrap",
        )
        assert closed["verdict"] == "ok"
        assert closed.get("status") == "closed"


class TestNewRoundSchemaGate:
    def test_mixed_schema_open_refused(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)

        # Plant a bootstrap-shaped finding (no apiVersion) before a new-round open.
        body = build_bootstrap_finding_comment_body(
            round_id="round-new",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        store.get("887").comments.append(
            CommentRecord(
                id="c-bootstrap",
                body=body,
                created_at="1",
                markers=["sw-doc-review"],
                author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
                revision="2020-01-01T00:00:00Z",
            )
        )
        store._persist()  # noqa: SLF001 — fixture store

        opened = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-new",
            ordered_comment_ids=["c-bootstrap"],
        )
        assert opened["verdict"] == "fail"
        assert opened["error"] == DOC_REVIEW_MIXED_SCHEMA

    def test_new_round_post_then_open_uses_v1(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)

        posted = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-v1",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        assert str(posted["revision"]).startswith(BODY_SHA256_V1_PREFIX)
        parsed = parse_doc_review_comment(get_fixture_store(transport_repo).get("887").comments[0].body)
        assert is_v1_finding_envelope(parsed)

        opened = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-v1",
            ordered_comment_ids=[posted["commentId"]],
        )
        assert opened["verdict"] == "ok", opened
        assert opened["status"] == "open"
        assert opened.get("pins"), opened
        assert not is_bootstrap_manifest(
            parse_review_round_block(get_fixture_store(transport_repo).get("887").body)
        )
        pin_rev = str(opened["pins"][0]["revision"])
        assert pin_rev.startswith(BODY_SHA256_V1_PREFIX)


class TestSynthesisRoundIdentityDoc:
    def test_synthesis_md_documents_same_round_id(self) -> None:
        # Bound to the phase worktree checkout of synthesis.md (R37).
        text = (
            Path(__file__).resolve().parents[3]
            / "core/skills/doc-review/references/synthesis.md"
        ).read_text(encoding="utf-8")
        assert "same `roundId`" in text or "same roundId" in text.lower() or "Reuse the open round" in text
        assert "post-then-open" in text
        assert "new `roundId`" in text or "new roundId" in text
