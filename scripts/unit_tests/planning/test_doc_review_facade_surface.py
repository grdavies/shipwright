"""PRD 341 phase 1 — facade-only doc-review surface (R1, R2, R34)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from credentials.model import CredentialRef, Principal, Resolution, ResolvedToken, Secret
from issues_lib import FIXTURE_GITHUB_PRINCIPAL_ID, IssuesClient, IssueCapabilityError, get_fixture_store
from planning_doc_review_transport import build_doc_review_comment_body
from planning_store_facade import (
    DOC_REVIEW_FACADE_OPERATIONS,
    doc_review_txn,
    facade_surface,
    load_workflow_config,
    post_review_finding,
)


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def facade_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    import planning_store_facade as psf

    resolved = Resolution.resolved(
        CredentialRef("fixture-doc-review"),
        ResolvedToken(Secret("fixture-token"), Principal(profile="fixture", account="fixture-bot-login")),
    )
    monkeypatch.setattr(psf, "resolve_issues_credential", lambda *a, **k: resolved)
    root = tmp_path
    _init_repo(root)
    cfg = {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "doc-review-fixture",
            }
        },
        "host": {"provider": "github"},
    }
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    get_fixture_store(root).clear()
    return root


class TestFacadeSurface:
    def test_facade_lists_five_doc_review_operations(self) -> None:
        surface = facade_surface()
        shipped = set(surface.get("shipped") or [])
        assert DOC_REVIEW_FACADE_OPERATIONS <= shipped
        assert "doc_review_txn" not in shipped

    def test_doc_review_txn_rejects_bootstrap_verbs(self, facade_repo: Path) -> None:
        cfg = load_workflow_config(facade_repo)
        out = doc_review_txn(
            facade_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="1",
            unit_id="prd-doc-review",
            round_id="round-1",
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "doc-review-use-facade-operation"
        assert set(out.get("facadeOperations") or []) == set(DOC_REVIEW_FACADE_OPERATIONS)


class TestAdapterIssueCommentGuard:
    def test_generic_issue_comment_refuses_doc_review_marker(
        self, facade_repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = IssuesClient(facade_repo, "github-issues")

        class LegacyBackend:
            def add_comment(
                self,
                issue_id: str,
                body: str,
                *,
                markers: list[str] | None = None,
                author_id: str = "",
            ):
                raise AssertionError("add_comment must not run for blocked doc-review post")

        monkeypatch.setattr(client, "_live_backend", lambda: LegacyBackend())
        body = build_doc_review_comment_body(
            round_id="round-1",
            persona="coherence",
            payload={"findings": []},
        )
        with pytest.raises(IssueCapabilityError, match="doc-review-comment-facade-required"):
            client.issue_comment("887", body, markers=["sw-doc-review"], author_id=FIXTURE_GITHUB_PRINCIPAL_ID)

    def test_facade_post_authorizes_adapter_issue_comment(self, facade_repo: Path) -> None:
        store = get_fixture_store(facade_repo)
        unit_id = "341-prd-doc-review-transport"
        record = store.create(
            title=f"PRD {unit_id}",
            body=f"<!-- sw-unit-id: {unit_id} -->\n# PRD\n",
            labels=["sw:prd", "sw:project:doc-review-fixture"],
            project_key="doc-review-fixture",
            artifact_type="prd",
            unit_id=unit_id,
        )
        store._issues["887"] = record
        store._persist()
        cfg = load_workflow_config(facade_repo)
        posted = post_review_finding(
            facade_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-facade",
            persona="coherence",
            payload={
                "reviewer": "coherence",
                "findings": [],
                "residual_risks": [],
                "deferred_questions": [],
            },
        )
        assert posted["verdict"] == "ok"
        assert posted.get("facadeOperation") == "post_review_finding"
