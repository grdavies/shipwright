"""Phase 5 — post-then-open, exhaustive pins, OCC vs stripped hash (PRD 341 R9–R13/R36)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credentials.model import CredentialRef, Principal, Resolution, ResolvedToken, Secret
from issues_lib import get_fixture_store
from planning_doc_review_transport import (
    DOC_REVIEW_MANIFEST_CONFLICT,
    DOC_REVIEW_PAGINATION_INCOMPLETE,
    DOC_REVIEW_UNPINNED_FINDINGS,
    default_manifest_idempotency_key,
    normalize_manifest_block,
    parse_review_round_block,
    strip_review_round_blocks,
    stripped_artifact_hash,
)
from planning_store_facade import load_workflow_config, open_review_manifest, post_review_finding
from unit_tests.planning.test_doc_review_transport_bootstrap import (
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


class TestPostThenOpenExhaustivePins:
    def test_open_writes_etag_guarded_body_with_exhaustive_pins(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        opened, comment_ids = _post_then_open(
            transport_repo,
            cfg,
            unit_id=unit_id,
            round_id="round-r9",
            personas=[
                ("coherence", _sample_payload("coherence")),
                ("security", _sample_payload("security")),
            ],
        )
        assert opened["verdict"] == "ok"
        assert opened["status"] == "open"
        assert [p["commentId"] for p in opened["pins"]] == comment_ids
        assert [p["ordinal"] for p in opened["pins"]] == [0, 1]
        assert opened["artifactRevision"]
        assert opened["artifactHash"]
        assert opened["artifactRevision"] != opened["artifactHash"]
        assert str(opened["artifactHash"]).startswith("body-sha256/v1:")
        assert opened["idempotencyKey"] == default_manifest_idempotency_key("round-r9")

        record = get_fixture_store(transport_repo).get("887")
        manifest = parse_review_round_block(record.body)
        assert manifest.get("apiVersion") == "shipwright.dev/doc-review-manifest/v1"
        assert manifest["artifactRevision"] == opened["artifactRevision"]
        assert manifest["artifactHash"] == stripped_artifact_hash(record.body)
        # Witness is present on the live body but excluded from the hash (R10/D12).
        assert "sw-doc-review-round" in record.body
        assert strip_review_round_blocks(record.body)
        assert "sw-doc-review-round" not in strip_review_round_blocks(record.body)

    def test_unpinned_same_round_finding_refuses_open(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        first = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-r36",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        second = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-r36",
            persona="security",
            payload=_sample_payload("security"),
        )
        assert first["verdict"] == "ok" and second["verdict"] == "ok"
        out = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-r36",
            ordered_comment_ids=[str(first["commentId"])],
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_UNPINNED_FINDINGS
        assert "sw-doc-review-round" not in get_fixture_store(transport_repo).get("887").body

    def test_permutation_order_is_honored(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        a = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-order",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        b = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-order",
            persona="security",
            payload=_sample_payload("security"),
        )
        reversed_ids = [str(b["commentId"]), str(a["commentId"])]
        opened = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-order",
            ordered_comment_ids=reversed_ids,
        )
        assert opened["verdict"] == "ok"
        assert [p["commentId"] for p in opened["pins"]] == reversed_ids


class TestOpenPaginationAndReplay:
    def test_incomplete_pagination_refuses_open(
        self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_doc_review_transport as transport

        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        posted = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-page-open",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        monkeypatch.setattr(transport, "comments_pagination_complete", lambda _record: False)
        out = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-page-open",
            ordered_comment_ids=[str(posted["commentId"])],
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_PAGINATION_INCOMPLETE

    def test_idempotent_open_replays_same_manifest(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        first, comment_ids = _post_then_open(
            transport_repo, cfg, unit_id=unit_id, round_id="round-replay-open"
        )
        second = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-replay-open",
            ordered_comment_ids=comment_ids,
            idempotency_key=default_manifest_idempotency_key("round-replay-open"),
        )
        assert second["verdict"] == "ok"
        assert second.get("idempotent") is True
        assert [p["commentId"] for p in second["pins"]] == [p["commentId"] for p in first["pins"]]
        assert second["artifactHash"] == first["artifactHash"]

    def test_conflicting_manifest_replay_fails_closed(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        opened, comment_ids = _post_then_open(
            transport_repo, cfg, unit_id=unit_id, round_id="round-conflict-open"
        )
        assert opened["verdict"] == "ok"
        # Conflicting immutable pin set under the same idempotency key.
        record = get_fixture_store(transport_repo).get("887")
        manifest = parse_review_round_block(record.body)
        manifest["pins"] = []
        from planning_doc_review_transport import upsert_review_round_block

        record.body = upsert_review_round_block(record.body, manifest)
        store = get_fixture_store(transport_repo)
        store._issues["887"] = record
        store._persist()
        out = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-open",
            ordered_comment_ids=comment_ids,
            idempotency_key=default_manifest_idempotency_key("round-conflict-open"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_MANIFEST_CONFLICT


class TestOccVersusStrippedHash:
    def test_artifact_revision_is_etag_not_hash(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        posted = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-occ",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        etag_at_open = get_fixture_store(transport_repo).get("887").etag
        opened = open_review_manifest(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-occ",
            ordered_comment_ids=[str(posted["commentId"])],
        )
        assert opened["verdict"] == "ok"
        assert opened["artifactRevision"] == etag_at_open
        assert opened["artifactHash"] != etag_at_open
        assert opened["artifactHash"] == stripped_artifact_hash(
            get_fixture_store(transport_repo).get("887").body
        )

    def test_dual_read_bootstrap_and_v1_pin_shapes(self) -> None:
        bootstrap = {
            "roundId": "r1",
            "status": "open",
            "unitId": "u",
            "issueId": "1",
            "pins": [
                {
                    "commentId": "c1",
                    "revision": "body-sha256/v1:abc",
                    "persona": "coherence",
                    "idempotencyKey": "r1:coherence",
                }
            ],
        }
        v1 = {
            "apiVersion": "shipwright.dev/doc-review-manifest/v1",
            "kind": "DocReviewManifest",
            "roundId": "r1",
            "unitId": "u",
            "issueId": "1",
            "pins": [
                {
                    "ordinal": 0,
                    "commentId": "c1",
                    "revisionToken": "body-sha256/v1:abc",
                    "personaId": "coherence",
                    "idempotencyKey": "r1:coherence",
                }
            ],
        }
        nb = normalize_manifest_block(bootstrap)
        nv = normalize_manifest_block(v1)
        assert nb["pins"][0]["revision"] == "body-sha256/v1:abc"
        assert nv["pins"][0]["revision"] == "body-sha256/v1:abc"
        assert nv["pins"][0]["persona"] == "coherence"
        # Comment-manifest dual-read is out of scope — body-block variants only (R11/D24).
        assert "sw:doc-review-manifest" not in json.dumps(nv)
