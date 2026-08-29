"""Phase 3 — post findings schema, idempotent replay, and size bounds (PRD 341 R5–R8/R38/R39)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from credentials.model import CredentialRef, Principal, Resolution, ResolvedToken, Secret
from issues_lib import FixtureIssuesStore, get_fixture_store
from planning_canonical import CommentRecord
from planning_doc_review_transport import (
    DOC_REVIEW_COMMENT_SIZE_CAP,
    DOC_REVIEW_FINDINGS_SCHEMA_INVALID,
    DOC_REVIEW_IDEMPOTENCY_AMBIGUOUS,
    DOC_REVIEW_PAGINATION_INCOMPLETE,
    DOC_REVIEW_PAYLOAD_TOO_LARGE,
    build_doc_review_comment_body,
    find_comments_by_idempotency_key,
    idempotency_key,
    payload_hash,
)
from planning_store_facade import (
    load_workflow_config,
    open_review_manifest,
    post_review_finding,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(*, provider: str = "github-issues", backend: str = "issue-store") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": backend,
                "issuesProvider": provider,
                "projectKey": "doc-review-fixture",
            }
        },
        "host": {"provider": "github"},
    }


def _fixture_bot(monkeypatch: pytest.MonkeyPatch) -> None:
    import planning_store_facade as psf

    resolved = Resolution.resolved(
        CredentialRef("fixture-doc-review"),
        ResolvedToken(Secret("fixture-token"), Principal(profile="fixture", account="fixture-bot-login")),
    )
    monkeypatch.setattr(psf, "resolve_issues_credential", lambda *a, **k: resolved)


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


def _seed_issue(store: FixtureIssuesStore, *, unit_id: str, issue_id: str = "887") -> None:
    record = store.create(
        title=f"PRD {unit_id}",
        body=f"<!-- sw-unit-id: {unit_id} -->\n# PRD\n",
        labels=["sw:prd", "sw:project:doc-review-fixture"],
        project_key="doc-review-fixture",
        artifact_type="prd",
        unit_id=unit_id,
    )
    store._issues[str(issue_id)] = record
    store._persist()


def _sample_payload(persona: str = "coherence") -> dict:
    return {
        "reviewer": persona,
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


def _open_round(repo: Path, *, unit_id: str, round_id: str, issue_id: str = "887") -> None:
    out = open_review_manifest(
        repo,
        load_workflow_config(repo),
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
    )
    assert out["verdict"] == "ok", out


def _post(
    repo: Path,
    *,
    unit_id: str,
    round_id: str,
    persona: str,
    payload: dict[str, Any],
    issue_id: str = "887",
) -> dict[str, Any]:
    return post_review_finding(
        repo,
        load_workflow_config(repo),
        issue_id=issue_id,
        unit_id=unit_id,
        round_id=round_id,
        persona=persona,
        payload=payload,
    )


class TestFindingsSchemaGate:
    def test_schema_invalid_refused_before_pin(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-schema")
        bad: dict[str, Any] = {"reviewer": "coherence", "findings": [{"title": "nope"}]}
        out = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-schema",
            persona="coherence",
            payload=bad,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_FINDINGS_SCHEMA_INVALID
        assert get_fixture_store(transport_repo).get("887").comments == []

    def test_reviewer_must_match_persona(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-persona")
        payload = _sample_payload("coherence")
        payload["reviewer"] = "security"
        out = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-persona",
            persona="coherence",
            payload=payload,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_FINDINGS_SCHEMA_INVALID
        assert out["detail"] == "reviewer-persona-mismatch"


class TestIdempotentReplay:
    def test_same_key_replays_one_comment(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-replay")
        first = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-replay",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert first["verdict"] == "ok"
        assert first["idempotent"] is False
        second = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-replay",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert second["verdict"] == "ok"
        assert second["idempotent"] is True
        assert second["commentId"] == first["commentId"]
        assert len(get_fixture_store(transport_repo).get("887").comments) == 1

    def test_json_key_order_does_not_conflict_replay(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-order")
        payload_a = _sample_payload("coherence")
        first = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-order",
            persona="coherence",
            payload=payload_a,
        )
        assert first["verdict"] == "ok"
        finding = payload_a["findings"][0]
        reordered_finding = {
            "evidence": finding["evidence"],
            "confidence": finding["confidence"],
            "suggested_fix": finding["suggested_fix"],
            "autofix_class": finding["autofix_class"],
            "finding_type": finding["finding_type"],
            "why_it_matters": finding["why_it_matters"],
            "section": finding["section"],
            "severity": finding["severity"],
            "title": finding["title"],
        }
        payload_b = {
            "deferred_questions": [],
            "residual_risks": [],
            "findings": [reordered_finding],
            "reviewer": "coherence",
        }
        assert list(payload_a.keys()) != list(payload_b.keys())
        assert payload_hash(payload_a) == payload_hash(payload_b)
        second = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-order",
            persona="coherence",
            payload=payload_b,
        )
        assert second["verdict"] == "ok"
        assert second["idempotent"] is True
        assert second["commentId"] == first["commentId"]

    def test_duplicate_idempotency_matches_fail_closed(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-dup")
        payload = _sample_payload("coherence")
        first = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-dup",
            persona="coherence",
            payload=payload,
        )
        assert first["verdict"] == "ok"
        record = get_fixture_store(transport_repo).get("887")
        body = build_doc_review_comment_body(
            round_id="round-dup",
            persona="coherence",
            payload=payload,
        )
        duplicate = CommentRecord(
            id="forged-dup",
            body=body,
            author_id=record.comments[0].author_id,
            created_at=record.comments[0].created_at,
            revision="forged-rev",
            markers=["sw-doc-review"],
        )
        record.comments.append(duplicate)
        store = get_fixture_store(transport_repo)
        store._issues["887"] = record
        store._persist()
        matches = find_comments_by_idempotency_key(
            list(get_fixture_store(transport_repo).get("887").comments),
            round_id="round-dup",
            key=idempotency_key("round-dup", "coherence"),
        )
        assert len(matches) == 2
        out = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-dup",
            persona="coherence",
            payload=payload,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_IDEMPOTENCY_AMBIGUOUS
        assert out["matchCount"] == 2

    def test_incomplete_pagination_fails_closed(
        self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import planning_doc_review_transport as transport

        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-page")
        monkeypatch.setattr(transport, "comments_pagination_complete", lambda _record: False)
        out = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-page",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_PAGINATION_INCOMPLETE


class TestPayloadSizeBound:
    def test_oversize_payload_is_typed_too_large(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        _open_round(transport_repo, unit_id=unit_id, round_id="round-size")
        payload = _sample_payload("coherence")
        payload["findings"][0]["evidence"] = ["x" * DOC_REVIEW_COMMENT_SIZE_CAP]
        body = build_doc_review_comment_body(
            round_id="round-size",
            persona="coherence",
            payload=payload,
        )
        assert len(body) > DOC_REVIEW_COMMENT_SIZE_CAP
        out = _post(
            transport_repo,
            unit_id=unit_id,
            round_id="round-size",
            persona="coherence",
            payload=payload,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_PAYLOAD_TOO_LARGE
        assert out["limit"] == DOC_REVIEW_COMMENT_SIZE_CAP
