"""PRD 341 phase 9 — capabilities, broker credentials, document-review budget (R3/R27–R29/R40)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credentials.model import CredentialRef, Resolution, ResolvedToken, Secret
from issues_lib import get_fixture_store
from planning_doc_review_transport import (
    DOC_REVIEW_BUDGET_EXHAUSTED,
    DOC_REVIEW_BUDGET_OPERATION,
    DOC_REVIEW_PROVIDER_UNSUPPORTED,
    doc_review_capabilities_for,
    missing_doc_review_capabilities,
    provider_unsupported,
    require_github_issue_store,
)
from planning_request_budget import load_ledger
from planning_store_facade import (
    load_workflow_config,
    post_review_finding,
    _doc_review_transport_txn,
)
from unit_tests.planning.test_doc_review_transport_bootstrap import (
    _fixture_bot,
    _init_repo,
    _issue_store_cfg,
    _sample_payload,
    _seed_issue,
)


@pytest.fixture
def facade_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    store = cfg.setdefault("planning", {}).setdefault("store", {})
    store["requestBudget"] = {
        "github-issues": {
            "maxCalls": 50,
            "maxPaginationDepth": 10,
            "alertThreshold": 0.9,
            "cacheTtlSeconds": 60,
        }
    }
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    get_fixture_store(root).clear()
    _fixture_bot(monkeypatch)
    return root


class TestCapabilityFloor:
    def test_github_advertises_doc_review_comments(self) -> None:
        caps = doc_review_capabilities_for("github-issues")
        assert caps["post"] is True
        assert caps["stableIds"] is True
        assert caps["verifiableAuthorPrincipal"] is True
        assert caps["completeFullBody"] is True
        assert caps["completePagination"] is True
        assert caps["stableApplicationId"] is False
        assert missing_doc_review_capabilities("github-issues") == []

    def test_non_github_preflight_unsupported(self) -> None:
        for provider in ("gitlab-issues", "jira", "linear", "notion", "none"):
            missing = missing_doc_review_capabilities(provider)
            assert missing
            out = provider_unsupported(provider=provider)
            assert out["error"] == DOC_REVIEW_PROVIDER_UNSUPPORTED
            assert out["missingCapabilities"] == missing
            blocked = require_github_issue_store(
                effective={"configured": "issue-store"},
                provider=provider,
            )
            assert blocked is not None
            assert blocked["error"] == DOC_REVIEW_PROVIDER_UNSUPPORTED

    def test_facade_refuses_linear_before_write(self, facade_repo: Path) -> None:
        cfg_path = facade_repo / ".cursor" / "workflow.config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["planning"]["store"]["issuesProvider"] = "linear"
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        loaded = load_workflow_config(facade_repo)
        out = post_review_finding(
            facade_repo,
            loaded,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-1",
            persona="product",
            payload=_sample_payload("product"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == DOC_REVIEW_PROVIDER_UNSUPPORTED
        assert "post" in (out.get("missingCapabilities") or [])


class TestDocumentReviewBudget:
    def test_listing_charges_document_review_class(self, facade_repo: Path) -> None:
        store = get_fixture_store(facade_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        cfg = load_workflow_config(facade_repo)
        posted = post_review_finding(
            facade_repo,
            cfg,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-budget",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert posted.get("verdict") == "ok", posted
        ledger = load_ledger(facade_repo)
        ops = (ledger.get("operations") or {}) if isinstance(ledger, dict) else {}
        providers = ledger.get("providers") if isinstance(ledger.get("providers"), dict) else {}
        gh = providers.get("github-issues") if isinstance(providers.get("github-issues"), dict) else {}
        gh_ops = gh.get("operations") if isinstance(gh.get("operations"), dict) else {}
        charged = int(ops.get(DOC_REVIEW_BUDGET_OPERATION) or gh_ops.get(DOC_REVIEW_BUDGET_OPERATION) or 0)
        assert charged >= 1

    def test_pagination_depth_exhaustion_typed(self, facade_repo: Path) -> None:
        cfg_path = facade_repo / ".cursor" / "workflow.config.json"
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        # post_review_finding lists twice (reconcile + refresh) — depth 1 fails closed (R40).
        cfg["planning"]["store"]["requestBudget"]["github-issues"]["maxPaginationDepth"] = 1
        cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
        store = get_fixture_store(facade_repo)
        unit_id = "341-prd-doc-review-transport"
        _seed_issue(store, unit_id=unit_id)
        loaded = load_workflow_config(facade_repo)
        out = post_review_finding(
            facade_repo,
            loaded,
            issue_id="887",
            unit_id=unit_id,
            round_id="round-depth",
            persona="coherence",
            payload=_sample_payload("coherence"),
        )
        assert out.get("verdict") == "fail"
        assert out.get("error") == DOC_REVIEW_BUDGET_EXHAUSTED
        assert out.get("detail") == "pagination-depth"

    def test_cache_cannot_authorize_open(self, facade_repo: Path) -> None:
        cfg = load_workflow_config(facade_repo)
        out = _doc_review_transport_txn(
            facade_repo,
            cfg,
            verb="doc-review-round-open",
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-1",
            authorize_from_cache=True,
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "doc-review-cache-not-authoritative"


class TestBrokerCredentials:
    def test_ambient_token_env_refused_without_fixture(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
        import planning_store_facade as psf

        _init_repo(tmp_path)
        cfg = _issue_store_cfg()
        cfg["planning"]["store"]["issues"] = {"tokenEnv": "DOC_REVIEW_TEST_TOKEN"}
        (tmp_path / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
        monkeypatch.setenv("DOC_REVIEW_TEST_TOKEN", "ambient-secret")
        monkeypatch.setattr(
            psf,
            "resolve_issues_credential",
            lambda *a, **k: Resolution.resolved(
                CredentialRef("tokenEnv:DOC_REVIEW_TEST_TOKEN"),
                ResolvedToken(Secret("ambient-secret")),
            ),
        )
        loaded = load_workflow_config(tmp_path)
        out = post_review_finding(
            tmp_path,
            loaded,
            issue_id="887",
            unit_id="341-prd-doc-review-transport",
            round_id="round-1",
            persona="product",
            payload=_sample_payload("product"),
        )
        assert out["verdict"] == "fail"
        assert out["error"] == "doc-review-credentials-ambient-refused"
