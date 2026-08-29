"""Phase 4 — whoami authorship and body-sha256/v1 revision tokens (PRD 341 R14–R18)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from issues_lib import FIXTURE_GITHUB_PRINCIPAL_ID, get_fixture_store
from planning.backends.issues import (
    assert_doc_review_authorship,
    resolve_doc_review_author_principal,
)
from planning_doc_review_transport import (
    BODY_SHA256_V1_PREFIX,
    body_sha256_v1,
    comment_revision_token,
    pin_from_comment,
)
from planning_store_facade import load_workflow_config, post_review_finding
from unit_tests.planning.test_doc_review_transport_bootstrap import (
    _doc_review,
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


class TestBodySha256V1:
    def test_crlf_normalization_stable(self) -> None:
        assert body_sha256_v1("a\r\nb") == body_sha256_v1("a\nb")
        assert body_sha256_v1("a\rb") == body_sha256_v1("a\nb")
        assert body_sha256_v1("x").startswith(BODY_SHA256_V1_PREFIX)

    def test_pin_revision_is_body_token_not_updated_at(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        cfg = load_workflow_config(transport_repo)
        posted = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-rev",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted["verdict"] == "ok"
        pin = posted["pin"]
        assert str(pin["revision"]).startswith(BODY_SHA256_V1_PREFIX)
        comment = get_fixture_store(transport_repo).get("887").comments[0]
        # Provider may still carry updated_at-style revision metadata — pin must ignore it.
        comment.revision = "2020-01-01T00:00:00Z"
        rebuilt = pin_from_comment(comment)
        assert rebuilt is not None
        assert rebuilt.revision == body_sha256_v1(comment.body)
        assert rebuilt.revision != comment.revision


class TestWhoamiAuthorship:
    def test_resolve_principal_from_fixture_whoami(self, transport_repo: Path) -> None:
        from issues_lib import IssuesClient

        client = IssuesClient(transport_repo, "github-issues")
        out = resolve_doc_review_author_principal(client)
        assert out["verdict"] == "ok"
        assert out["authorPrincipal"] == FIXTURE_GITHUB_PRINCIPAL_ID
        assert out["stableApplicationId"] is False

    def test_payload_claimed_author_rejected(self, transport_repo: Path) -> None:
        rejected = assert_doc_review_authorship(
            expected_principal=FIXTURE_GITHUB_PRINCIPAL_ID,
            comment_author_id=FIXTURE_GITHUB_PRINCIPAL_ID,
            payload_claimed_author="spoof-bot",
        )
        assert rejected is not None
        assert rejected["error"] == "doc-review-authorship-rejected"
        assert rejected["detail"] == "payload-claimed-author"

    def test_post_refuses_spoofed_payload_author(self, transport_repo: Path) -> None:
        store = get_fixture_store(transport_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        cfg = load_workflow_config(transport_repo)
        payload = _sample_payload("coherence")
        payload["authorId"] = "999999"
        out = post_review_finding(
            transport_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-auth",
            persona="coherence",
            payload=payload,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "doc-review-authorship-rejected"

    def test_whoami_mismatch_rejected(self) -> None:
        rejected = assert_doc_review_authorship(
            expected_principal="111",
            comment_author_id="222",
        )
        assert rejected is not None
        assert rejected["detail"] == "whoami-mismatch"
