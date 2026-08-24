"""PRD 327 phase 2 — Notion provider registration, issues_lib gating, schema/rate-limit (hermetic)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_http
import issues_lib
import planning_notion_client as pnc
import planning_store as ps
from planning.providers import notion as notion_provider


def _notion_cfg(*, with_database: bool = True) -> dict[str, Any]:
    issues: dict[str, Any] = {"tokenEnv": "ISSUES_NOTION_TOKEN"}
    if with_database:
        issues["notionDatabaseId"] = "db-fixture-00000000000000000000000000000001"
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "notion",
                "projectKey": "planning",
                "issues": issues,
            }
        }
    }


def test_notion_live_client_wired() -> None:
    assert pnc.LIVE_CLIENT is True
    assert notion_provider.live_client_wired() is True


def test_notion_recognized_not_shipped() -> None:
    assert "notion" in ps.ISSUES_PROVIDERS
    assert "notion" not in ps.SHIPPED_ISSUES_PROVIDERS


def test_registration_footprint_notion_surface() -> None:
    footprint = ps.issues_provider_registration_footprint()
    assert footprint["notion"]["liveClientWired"] is True
    assert footprint["notion"]["promotionGatedBy"] == ["conformance", "docs-gate"]
    assert footprint["rateLimitMap"]["notion"] == "notion"
    assert footprint["capabilityIndexIds"]["notion"] == "provider.providers.issues.notion"
    assert footprint["recognitionVsShipped"]["notion"] == {
        "recognized": True,
        "shipped": False,
        "deferred": False,
    }


def test_doctor_notion_recognized_not_shipped(tmp_path: Path) -> None:
    result = ps.doctor_issues_provider_stub(tmp_path, _notion_cfg())
    assert result["verdict"] == "pass"
    assert result["notice"] == "notion-recognized-not-shipped"


def test_doctor_notion_stub_refused_when_client_unwired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notion_provider, "live_client_wired", lambda: False)
    # Re-import facade constants would be stale; doctor uses live ISSUES_PROVIDERS from import time.
    # Stub refused path: configure notion while module reports unwired via doctor_stub issues_providers.
    result = notion_provider.doctor_stub_result(
        tmp_path,
        provider="notion",
        issues_providers=frozenset({"github-issues"}),
        shipped_providers=ps.SHIPPED_ISSUES_PROVIDERS,
    )
    assert result is not None
    assert result["verdict"] == "fail"
    assert result["error"] == "notion-stub-refused"


def test_issues_lib_notion_unshipped_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SW_ISSUES_FIXTURE", raising=False)
    client = issues_lib.IssuesClient(tmp_path, "notion")
    with pytest.raises(issues_lib.IssueCapabilityError, match="not shipped"):
        client._live_backend()


def test_issues_http_notion_ratelimit_profile() -> None:
    cfg = _notion_cfg()
    resolved = issues_http.resolve_issues_rate_limit(cfg, issues_provider="notion")
    assert resolved["mutatingMinDelayMs"] == 334
    assert issues_http.issues_ratelimit_provider("notion") == "notion"


def test_notion_retryable_errors() -> None:
    assert issues_http._notion_retryable_error(
        409,
        json.dumps({"code": "conflict_error"}),
    )
    assert issues_http._notion_retryable_error(
        502,
        json.dumps({"code": "gateway_timeout"}),
    )
    assert not issues_http._notion_retryable_error(
        400,
        json.dumps({"code": "validation_error"}),
    )
    assert issues_http._notion_validation_error(
        400,
        json.dumps({"code": "validation_error"}),
    )


def test_request_budget_notion_defaults(tmp_git_repo: Path) -> None:
    from planning_request_budget import RequestBudgetLedger

    (tmp_git_repo / "workflow.config.json").write_text(
        json.dumps(_notion_cfg()) + "\n",
        encoding="utf-8",
    )
    ledger = RequestBudgetLedger.from_config(tmp_git_repo, "notion")
    assert ledger.max_calls == 300
    assert ledger.max_pagination_depth == 5
