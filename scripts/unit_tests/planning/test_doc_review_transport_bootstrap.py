"""Bootstrap tests for issue-store doc-review comment transport (PRD 341 slice)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from credentials.model import CredentialRef, Principal, Resolution, ResolvedToken, Secret
from issues_broker import IssueCommentAuthorshipMismatch
from issues_lib import FIXTURE_GITHUB_PRINCIPAL_ID, FixtureIssuesStore, IssueRevisionConflict, IssuesClient, get_fixture_store
from planning_canonical import CommentRecord, IssueSnapshot, canonical_hash
from planning_doc_review_transport import (
    DOC_REVIEW_COMMENT_DRIFT,
    DOC_REVIEW_ROUND_MALFORMED,
    DOC_REVIEW_TRANSPORT_UNAVAILABLE,
    build_doc_review_comment_body,
    idempotency_key,
    inspect_review_round_block,
    parse_doc_review_comment,
    parse_review_round_block,
    payload_hash,
    render_review_round_block,
    upsert_review_round_block,
    validate_doc_review_envelope,
)
from planning_github_client import GitHubIssuesClient, _parse_comment
from planning_store_facade import (
    complete_review_round,
    doc_review_txn,
    facade_surface,
    load_workflow_config,
    open_review_manifest,
    post_review_finding,
    read_review_manifest,
    verify_review_manifest,
)

_DOC_REVIEW_FACADE_BY_VERB = {
    "doc-review-round-open": open_review_manifest,
    "doc-review-round-post": post_review_finding,
    "doc-review-round-read": read_review_manifest,
    "doc-review-round-verify": verify_review_manifest,
    "doc-review-round-close": complete_review_round,
}


def _doc_review(
    repo: Path,
    cfg: dict,
    *,
    verb: str,
    issue_id: str | None = None,
    unit_id: str | None = None,
    round_id: str | None = None,
    persona: str | None = None,
    payload: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    facade_fn = _DOC_REVIEW_FACADE_BY_VERB.get(verb)
    if facade_fn is None:
        return doc_review_txn(
            repo,
            cfg,
            verb=verb,
            issue_id=issue_id,
            unit_id=unit_id,
            round_id=round_id,
            persona=persona,
            payload=payload,
            dry_run=dry_run,
        )
    kwargs: dict[str, Any] = {
        "issue_id": issue_id,
        "unit_id": unit_id,
        "round_id": round_id,
        "dry_run": dry_run,
    }
    if verb == "doc-review-round-post":
        kwargs["persona"] = persona
        kwargs["payload"] = payload
    return facade_fn(repo, cfg, **kwargs)


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


class TestCapabilityGate:
    def test_file_store_fails_closed(self, transport_repo: Path) -> None:
        cfg = _issue_store_cfg(backend="file-store")
        (transport_repo / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
        out = _doc_review(
            transport_repo,
            load_workflow_config(transport_repo),
            verb="doc-review-round-open",
            issue_id="1",
            unit_id="prd-doc-review",
            round_id="round-1",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_TRANSPORT_UNAVAILABLE

    def test_jira_provider_fails_closed(self, transport_repo: Path) -> None:
        cfg = _issue_store_cfg(provider="jira")
        (transport_repo / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
        out = _doc_review(
            transport_repo,
            load_workflow_config(transport_repo),
            verb="doc-review-round-open",
            issue_id="1",
            unit_id="prd-doc-review",
            round_id="round-1",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_TRANSPORT_UNAVAILABLE


class TestLifecycle:
    def test_post_open_read_verify_close_happy_path(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")

        opened = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-a",
        )
        assert opened["verdict"] == "ok"
        assert opened["status"] == "open"

        posted = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-a",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        assert posted["commentId"]
        assert posted["authorId"] == FIXTURE_GITHUB_PRINCIPAL_ID

        retry = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-a",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert retry["verdict"] == "ok"
        assert retry["idempotent"] is True
        assert retry["commentId"] == posted["commentId"]

        read_back = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-read",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-a",
        )
        assert read_back["verdict"] == "ok"
        assert len(read_back["pins"]) == 1
        assert read_back["pins"][0]["persona"] == "coherence"
        assert read_back["pins"][0]["bodySnapshot"]

        verified = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-a",
        )
        assert verified["verdict"] == "ok"

        closed = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-a",
        )
        assert closed["verdict"] == "ok"
        assert closed["status"] == "closed"

    def test_post_conflict_on_changed_payload(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-b",
        )
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-b",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        changed = _sample_payload("coherence")
        changed["findings"][0]["title"] = "Different title"
        conflict = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-b",
            persona="coherence",
            payload=changed,
        )
        assert conflict["verdict"] == "fail"
        assert conflict["error"] == "doc-review-idempotency-conflict"


class TestDriftDetection:
    def _open_and_post(self, repo: Path, cfg: dict, unit_id: str) -> None:
        _doc_review(
            repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
        )
        _doc_review(
            repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )

    def test_edit_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments[0].body = record.comments[0].body.replace("Example finding", "Edited finding")
        record.comments[0].revision = "edited-revision"
        store._persist()
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "malformed"
        assert out["detail"] == "payload-hash-mismatch"

    def test_delete_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments.clear()
        store._persist()
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "delete"

    def test_new_marked_comment_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        body = build_doc_review_comment_body(
            round_id="round-drift",
            persona="product",
            payload=_sample_payload("product"),
        )
        record.comments.append(
            CommentRecord(
                id="comment-extra",
                body=body,
                created_at="999",
                markers=["sw-doc-review"],
                author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
                revision="999",
            )
        )
        store._persist()
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "added"

    def test_author_mismatch_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments[0].author_id = "forged-user"
        store._persist()
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "author-mismatch"

    def test_malformed_marker_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments[0].body = "<!-- sw-doc-review -->\nnot-json\n<!-- /sw-doc-review -->"
        store._persist()
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-drift",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "malformed"

    def test_issue_unit_mismatch(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id="wrong-unit",
            round_id="round-x",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "issue-unit-mismatch"

    def test_post_author_mismatch_returns_structured_drift(
        self,
        transport_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-auth-mismatch",
        )

        def _raise_mismatch(
            self: IssuesClient,
            issue_id: str,
            body: str,
            *,
            markers: list[str] | None = None,
            author_id: str = "",
        ) -> CommentRecord:
            raise IssueCommentAuthorshipMismatch(
                "doc-review authorship mismatch",
                expected=FIXTURE_GITHUB_PRINCIPAL_ID,
                actual="999",
                comment_id="comment-forged",
            )

        monkeypatch.setattr(IssuesClient, "issue_comment", _raise_mismatch)
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-auth-mismatch",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "author-mismatch"
        assert out["commentId"] == "comment-forged"
        assert out["expectedAuthorId"] == FIXTURE_GITHUB_PRINCIPAL_ID
        assert out["actualAuthorId"] == "999"

    def test_manifest_update_fail_closed_on_revision_conflict(
        self,
        transport_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-bind",
        )
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-bind",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        update_calls = {"count": 0}
        original_update = IssuesClient.issue_update

        def _flaky_update(self: IssuesClient, issue_id: str, **kwargs: Any) -> Any:
            update_calls["count"] += 1
            raise IssueRevisionConflict("revision-conflict", expected="etag-a", actual="etag-b")

        monkeypatch.setattr(IssuesClient, "issue_update", _flaky_update)
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-bind",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "revision-conflict"
        assert update_calls["count"] == 1


class TestCanonicalExclusion:
    def test_sw_doc_review_excluded_from_canonical_hash(self) -> None:
        body = build_doc_review_comment_body(
            round_id="round-hash",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        comment = CommentRecord(
            id="c1",
            body=body,
            created_at="1",
            markers=["sw-doc-review"],
            author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
            revision="1",
        )
        snap = IssueSnapshot(
            title="PRD",
            body="<!-- sw-unit-id: u -->\n# Body",
            state="open",
            labels=["sw:prd"],
            comments=[comment],
        )
        with_comment = canonical_hash(snap)
        snap_no_review = IssueSnapshot(
            title=snap.title,
            body=snap.body,
            state=snap.state,
            labels=snap.labels,
            comments=[],
        )
        assert with_comment == canonical_hash(snap_no_review)

    def test_marker_parse_roundtrip(self) -> None:
        body = build_doc_review_comment_body(
            round_id="round-parse",
            persona="feasibility",
            payload=_sample_payload("feasibility"),
        )
        parsed = parse_doc_review_comment(body)
        assert parsed is not None
        assert parsed["round"] == "round-parse"
        assert parsed["persona"] == "feasibility"
        assert parsed["payload"]["reviewer"] == "feasibility"


class TestMultiRoundCoexistence:
    def test_two_rounds_do_not_cross_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")

        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-one",
        )
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-one",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        closed_one = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-one",
        )
        assert closed_one["verdict"] == "ok"

        opened_two = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-two",
        )
        assert opened_two["verdict"] == "ok"

        posted_two = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-two",
            persona="product",
            payload=_sample_payload("product"),
        )
        assert posted_two["verdict"] == "ok"

        verified = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-two",
        )
        assert verified["verdict"] == "ok"


class TestCloseIntegrity:
    def _open_and_post(self, repo: Path, cfg: dict, unit_id: str, round_id: str = "round-close") -> None:
        _doc_review(
            repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
        )
        _doc_review(
            repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id=round_id,
            persona="coherence",
            payload=_sample_payload("coherence"),
        )

    def test_close_refuses_on_drift(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)

        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments[0].body = record.comments[0].body.replace("Example finding", "Edited finding")
        record.comments[0].revision = "edited-revision"
        store._persist()

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-close",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "malformed"
        assert out["detail"] == "payload-hash-mismatch"

    def test_close_idempotent_when_already_closed(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_and_post(transport_repo, cfg, unit_id)

        first = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-close",
        )
        assert first["verdict"] == "ok"
        assert first.get("idempotent") is not True

        second = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-close",
        )
        assert second["verdict"] == "ok"
        assert second.get("idempotent") is True
        assert second["status"] == "closed"


class TestUnpinnedCommentRecovery:
    def test_idempotent_post_reconciles_missing_pin(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")

        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-unpin",
        )
        posted = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-unpin",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"

        store = get_fixture_store(transport_repo)
        record = store.get("887")
        manifest = parse_review_round_block(record.body)
        manifest["pins"] = []
        record.body = upsert_review_round_block(record.body, manifest)
        store._persist()

        retry = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-unpin",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert retry["verdict"] == "ok"
        assert retry["idempotent"] is True
        assert retry.get("reconciled") is True
        assert retry["commentId"] == posted["commentId"]

        read_back = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-read",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-unpin",
        )
        assert read_back["verdict"] == "ok"
        assert len(read_back["pins"]) == 1


class TestGitHubPrincipalLookup:
    def test_fixture_authenticated_principal_id(self, transport_repo: Path) -> None:
        client = IssuesClient(transport_repo, "github-issues")
        assert client.authenticated_principal_id() == FIXTURE_GITHUB_PRINCIPAL_ID

    def test_parse_comment_uses_numeric_id_not_login(self) -> None:
        comment = _parse_comment(
            {
                "id": 42,
                "body": "hello",
                "created_at": "2020-01-01T00:00:00Z",
                "updated_at": "2020-01-02T00:00:00Z",
                "user": {"id": 12345, "login": "octocat"},
            }
        )
        assert comment.author_id == "12345"

    def test_github_user_endpoint_returns_immutable_id(self, transport_repo: Path) -> None:
        client = MagicMock(spec=GitHubIssuesClient)
        client.api_base = "https://api.github.com"
        client.headers = {}
        client._http_json = MagicMock(return_value={"id": 987654, "login": "shipwright-bot"})
        principal_id = GitHubIssuesClient.authenticated_principal_id(client)
        assert principal_id == "987654"
        client._http_json.assert_called_once_with("GET", "https://api.github.com/user", {})


class TestPaginatedCommentReads:
    def test_list_comments_paginates_until_short_page(self, transport_repo: Path) -> None:
        client = MagicMock(spec=GitHubIssuesClient)
        client.headers = {}

        page_re = re.compile(r"[?&]page=(\d+)&?")

        def _fake_http(method: str, url: str, headers: dict[str, str]) -> Any:
            assert method == "GET"
            match = page_re.search(url)
            page = int(match.group(1)) if match else 0
            if page == 1:
                return [
                    {"id": idx, "body": "a", "created_at": "1", "updated_at": "1", "user": {"id": 1}}
                    for idx in range(1, 101)
                ]
            if page == 2:
                return [{"id": 101, "body": "b", "created_at": "2", "updated_at": "2", "user": {"id": 1}}]
            return []

        client._http_json = MagicMock(side_effect=_fake_http)
        client._issue_url = MagicMock(side_effect=lambda num, suffix="": f"https://example/issues/{num}{suffix}")

        comments = GitHubIssuesClient._list_comments(client, 99)
        assert len(comments) == 101
        assert comments[0].id == "1"
        assert comments[-1].id == "101"
        assert client._http_json.call_count == 2


def _tamper_manifest(repo: Path, issue_id: str, **fields: Any) -> None:
    store = get_fixture_store(repo)
    record = store.get(issue_id)
    manifest = parse_review_round_block(record.body)
    manifest.update(fields)
    record.body = upsert_review_round_block(record.body, manifest)
    store._persist()


def _tampered_envelope_body(
    *,
    round_id: str,
    persona: str,
    payload: dict,
    bad_hash: bool = False,
    bad_key: bool = False,
) -> str:
    envelope = {
        "round": round_id,
        "persona": persona,
        "idempotencyKey": "tampered-key" if bad_key else idempotency_key(round_id, persona),
        "payloadHash": "deadbeef" if bad_hash else payload_hash(payload),
        "payload": payload,
    }
    raw = json.dumps(envelope, indent=2, sort_keys=True, ensure_ascii=False)
    return (
        "<!-- sw-doc-review -->\n"
        f"```json\n{raw}\n```\n"
        "<!-- /sw-doc-review -->\n"
    )


class TestIssuesClientCommentBackwardCompat:
    def test_issue_comment_omits_empty_author_id(self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        class LegacyBackend:
            def add_comment(self, issue_id: str, body: str, *, markers: list[str] | None = None) -> CommentRecord:
                captured["kwargs"] = {"markers": markers}
                return CommentRecord(id="c0", body=body, created_at="1", markers=list(markers or []))

        client = IssuesClient(transport_repo, "github-issues")
        monkeypatch.setattr(client, "_live_backend", lambda: LegacyBackend())
        client.issue_comment("887", "plain note", markers=["note"])
        assert captured["kwargs"] == {"markers": ["note"]}

    def test_issue_comment_passes_author_id_when_set(self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, Any] = {}

        class GitHubBackend:
            def add_comment(
                self,
                issue_id: str,
                body: str,
                *,
                markers: list[str] | None = None,
                author_id: str = "",
            ) -> CommentRecord:
                captured["kwargs"] = {"markers": markers, "author_id": author_id}
                return CommentRecord(
                    id="c1",
                    body=body,
                    created_at="1",
                    markers=list(markers or []),
                    author_id=author_id,
                )

        client = IssuesClient(transport_repo, "github-issues")
        monkeypatch.setattr(client, "_live_backend", lambda: GitHubBackend())
        from planning.backends.issues import doc_review_facade_issue_comment_scope

        with doc_review_facade_issue_comment_scope():
            client.issue_comment(
                "887",
                "review",
                markers=["sw-doc-review"],
                author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
            )
        assert captured["kwargs"]["author_id"] == FIXTURE_GITHUB_PRINCIPAL_ID


class TestManifestBinding:
    def _open_round(self, repo: Path, cfg: dict, unit_id: str) -> None:
        _doc_review(
            repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bind",
        )

    def test_tampered_manifest_unit_id_fails_verify(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_round(transport_repo, cfg, unit_id)
        _tamper_manifest(transport_repo, "887", unitId="wrong-unit")

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bind",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "issue-unit-mismatch"

    def test_tampered_manifest_issue_id_fails_read(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_round(transport_repo, cfg, unit_id)
        _tamper_manifest(transport_repo, "887", issueId="999")

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-read",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bind",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "issue-id-mismatch"

    def test_idempotent_open_checks_manifest_binding(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._open_round(transport_repo, cfg, unit_id)
        _tamper_manifest(transport_repo, "887", unitId="wrong-unit")

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-bind",
        )
        assert out["verdict"] == "fail"
        assert out["driftKind"] == "issue-unit-mismatch"


class TestMalformedMarkedComments:
    def test_unparseable_marked_comment_fails_verify(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-malformed",
        )
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments.append(
            CommentRecord(
                id="comment-bad",
                body="<!-- sw-doc-review -->\nnot-json\n<!-- /sw-doc-review -->",
                created_at="999",
                markers=["sw-doc-review"],
                author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
                revision="999",
            )
        )
        store._persist()

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-malformed",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "malformed"
        assert out["detail"] == "envelope-unparseable"


class TestEnvelopeConsistency:
    def test_validate_doc_review_envelope_detects_hash_and_key_tamper(self) -> None:
        payload = _sample_payload("coherence")
        body = _tampered_envelope_body(round_id="round-env", persona="coherence", payload=payload, bad_hash=True)
        parsed = parse_doc_review_comment(body)
        assert parsed is not None
        assert validate_doc_review_envelope(parsed) == "payload-hash-mismatch"

        body_key = _tampered_envelope_body(round_id="round-env", persona="coherence", payload=payload, bad_key=True)
        parsed_key = parse_doc_review_comment(body_key)
        assert parsed_key is not None
        assert validate_doc_review_envelope(parsed_key) == "idempotency-key-mismatch"

    def test_verify_fails_on_payload_hash_tamper(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-env",
        )
        payload = _sample_payload("coherence")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-env",
            persona="coherence",
            payload=payload,
        )
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments[0].body = _tampered_envelope_body(
            round_id="round-env",
            persona="coherence",
            payload=payload,
            bad_hash=True,
        )
        store._persist()

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-env",
        )
        assert out["verdict"] == "fail"
        assert out["driftKind"] == "malformed"
        assert out["detail"] == "payload-hash-mismatch"

    def test_verify_fails_on_idempotency_key_tamper(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-env2",
        )
        payload = _sample_payload("product")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-env2",
            persona="product",
            payload=payload,
        )
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments[0].body = _tampered_envelope_body(
            round_id="round-env2",
            persona="product",
            payload=payload,
            bad_key=True,
        )
        store._persist()

        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-verify",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-env2",
        )
        assert out["verdict"] == "fail"
        assert out["driftKind"] == "malformed"
        assert out["detail"] == "idempotency-key-mismatch"


class TestRevisionConflictHandling:
    @staticmethod
    def _force_update_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(self: IssuesClient, issue_id: str, **kwargs: Any) -> Any:
            raise IssueRevisionConflict(
                "revision-conflict",
                expected="expected-etag",
                actual="actual-etag",
            )

        monkeypatch.setattr(IssuesClient, "issue_update", _boom)

    def test_open_revision_conflict(self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        self._force_update_conflict(monkeypatch)
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-open",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "revision-conflict"
        assert out["detail"] == {"expected": "expected-etag", "actual": "actual-etag"}

    def test_post_pin_update_revision_conflict(self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-post",
        )
        posted = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-post",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        _tamper_manifest(transport_repo, "887", pins=[])
        self._force_update_conflict(monkeypatch)
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-post",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "revision-conflict"

    def test_close_revision_conflict(self, transport_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-close",
        )
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-close",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        self._force_update_conflict(monkeypatch)
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-close",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-conflict-close",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "revision-conflict"

    def test_read_detects_binding_after_refresh(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-toctou-read",
        )
        _tamper_manifest(transport_repo, "887", unitId="tampered-unit")
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-read",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-toctou-read",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_COMMENT_DRIFT
        assert out["driftKind"] == "issue-unit-mismatch"

    def test_concurrent_pin_changes_not_overwritten(
        self,
        transport_repo: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-concurrent-pins",
        )
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-concurrent-pins",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        manifest = parse_review_round_block(record.body)
        concurrent_pin = {
            "commentId": "concurrent-comment",
            "revision": "rev-concurrent",
            "authorId": FIXTURE_GITHUB_PRINCIPAL_ID,
            "persona": "security",
            "idempotencyKey": "round-concurrent-pins:security",
            "payloadHash": payload_hash(_sample_payload("security")),
            "bodyDigest": "deadbeef",
        }
        manifest["pins"] = list(manifest.get("pins") or []) + [concurrent_pin]
        record.body = upsert_review_round_block(record.body, manifest)
        record.touch()
        store._persist()
        pins_before = list(parse_review_round_block(record.body).get("pins") or [])

        def _conflict_on_manifest_update(self: IssuesClient, issue_id: str, **kwargs: Any) -> Any:
            body = kwargs.get("body") or ""
            if "sw-doc-review-round" in body:
                raise IssueRevisionConflict("revision-conflict", expected="stale", actual="fresh")
            return IssuesClient.issue_update(self, issue_id, **kwargs)

        monkeypatch.setattr(IssuesClient, "issue_update", _conflict_on_manifest_update)
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-concurrent-pins",
            persona="product",
            payload=_sample_payload("product"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "revision-conflict"
        store = get_fixture_store(transport_repo)
        pins_after = list(parse_review_round_block(store.get("887").body).get("pins") or [])
        assert pins_after == pins_before


class TestReviewRoundBlockParsing:
    def test_parses_json_with_brace_arrow_sequence_in_string(self) -> None:
        block = {
            "roundId": "round-edge",
            "status": "open",
            "unitId": "u",
            "issueId": "1",
            "note": "literal } --> inside string",
            "pins": [],
        }
        body = f"# PRD\n\n{render_review_round_block(block)}"
        parsed, err = inspect_review_round_block(body)
        assert err is None
        assert parsed["roundId"] == "round-edge"
        assert parsed["note"] == "literal } --> inside string"

    def test_duplicate_round_blocks_fail_closed(self) -> None:
        block = {"roundId": "r1", "status": "open", "pins": []}
        body = render_review_round_block(block) + "\n" + render_review_round_block(block)
        _manifest, err = inspect_review_round_block(body)
        assert err == "duplicate-round-block"

    def test_upsert_leaves_single_round_block(self) -> None:
        block_a = {"roundId": "r1", "status": "open", "pins": []}
        block_b = {"roundId": "r2", "status": "closed", "pins": [{"commentId": "c1"}]}
        body = upsert_review_round_block("# body", block_a)
        updated = upsert_review_round_block(body, block_b)
        manifest, err = inspect_review_round_block(updated)
        assert err is None
        assert manifest["roundId"] == "r2"
        assert updated.count("<!-- sw-doc-review-round -->") == 1

    def test_legacy_inline_round_block_rejected(self) -> None:
        body = '# PRD\n<!-- sw-doc-review-round: {"roundId":"legacy"} -->'
        _manifest, err = inspect_review_round_block(body)
        assert err == "legacy-inline-round-block"


class TestIdempotencyRefresh:
    def test_post_discovers_concurrent_existing_comment(self, transport_repo: Path) -> None:
        cfg = load_workflow_config(transport_repo)
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id, issue_id="887")
        _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-idempotent-refresh",
        )
        payload = _sample_payload("coherence")
        body = build_doc_review_comment_body(round_id="round-idempotent-refresh", persona="coherence", payload=payload)
        store = get_fixture_store(transport_repo)
        record = store.get("887")
        record.comments.append(
            CommentRecord(
                id="concurrent-c1",
                body=body,
                created_at="2",
                markers=["sw-doc-review"],
                author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
                revision="2",
            )
        )
        store._persist()
        out = _doc_review(
            transport_repo,
            cfg,
            verb="doc-review-round-post",
            issue_id="887",
            unit_id=unit_id,
            round_id="round-idempotent-refresh",
            persona="coherence",
            payload=payload,
        )
        assert out["verdict"] == "ok"
        assert out["idempotent"] is True
        assert out["commentId"] == "concurrent-c1"
        store = get_fixture_store(transport_repo)
        assert len(store.get("887").comments) == 1


class TestDocReviewCli:
    def test_malformed_payload_json_returns_structured_fail(self, transport_repo: Path) -> None:
        proc = subprocess.run(
            [
                "python3",
                str(Path(__file__).resolve().parents[2] / "planning_store.py"),
                "--root",
                str(transport_repo),
                "post-review-finding",
                "--issue-id",
                "887",
                "--unit-id",
                "341-prd-doc-review-transport",
                "--round-id",
                "round-cli",
                "--persona",
                "coherence",
                "--payload-json",
                "{not-json",
            ],
            cwd=str(transport_repo),
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "SW_ISSUES_FIXTURE": "1"},
        )
        assert proc.returncode == 20
        payload = json.loads(proc.stdout)
        assert payload["verdict"] == "fail"
        assert payload["error"] == "invalid-payload-json"
