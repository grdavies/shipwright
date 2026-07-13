"""PRD 066 phase 3 — Linear client, team auth, dual budgets (R9, R11–R14, R23)."""
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
import planning_linear_client as plc
import planning_request_budget as prb
import planning_store as ps


def _cfg(
    *,
    team_key: str | None = "ENG",
    team_id: str | None = None,
    auth_mode: str = "api-key",
    token_env: str = "ISSUES_LINEAR_TOKEN",
    oauth_shared_ci_exception: bool | None = None,
) -> dict[str, Any]:
    issues: dict[str, Any] = {
        "tokenEnv": token_env,
        "authMode": auth_mode,
    }
    if team_key is not None:
        issues["teamKey"] = team_key
    if team_id is not None:
        issues["teamId"] = team_id
    if oauth_shared_ci_exception is not None:
        issues["oauthSharedCiException"] = oauth_shared_ci_exception
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "issues": issues,
                "requestBudget": {
                    "linear": {
                        "maxCalls": 50,
                        "maxComplexityPoints": 10000,
                        "alertThreshold": 0.8,
                        "cacheTtlSeconds": 60,
                    }
                },
            }
        }
    }


def test_r9_live_client_present_before_issues_providers_recognition() -> None:
    """R9/R12 — live GraphQL client module exists; linear recognized only when wired."""
    assert plc.LIVE_CLIENT is True
    assert callable(plc.graphql)
    assert "linear" in ps.ISSUES_PROVIDERS
    assert "linear" not in ps.SHIPPED_ISSUES_PROVIDERS
    assert ps.DEFAULT_ISSUES_TOKEN_ENV.get("linear") == "ISSUES_LINEAR_TOKEN"
    assert "linear" in issues_http.ISSUES_PROVIDER_TO_RATELIMIT


def test_r11_missing_both_team_keys_fails_closed() -> None:
    """R11 — at least one of teamKey/teamId required."""
    cfg = _cfg(team_key=None, team_id=None)
    with pytest.raises(plc.LinearTeamConfigError) as exc:
        plc.resolve_team_scope(cfg)
    assert exc.value.code == "missing-team-scope"


def test_r11_team_probe_mismatch_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R11 — when both teamKey and teamId set, probe fails if they resolve differently."""
    cfg = _cfg(team_key="ENG", team_id="team_OTHER")
    monkeypatch.setenv("ISSUES_LINEAR_TOKEN", "lin_test_token_not_real")

    def fake_graphql(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "data": {
                "teams": {
                    "nodes": [{"id": "team_ENG", "key": "ENG", "name": "Engineering"}]
                }
            }
        }

    monkeypatch.setattr(plc, "graphql", fake_graphql)
    result = plc.probe_team_scope(tmp_path, cfg, token="lin_test_token_not_real")
    assert result["verdict"] == "fail"
    assert result["error"] == "team-scope-mismatch"


def test_r11_team_probe_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R11 — matching teamKey/teamId probe succeeds; over-scoped key refused when detectable."""
    cfg = _cfg(team_key="ENG", team_id="team_ENG")
    monkeypatch.setenv("ISSUES_LINEAR_TOKEN", "lin_test_token_not_real")

    def fake_graphql(*_a: Any, **_k: Any) -> dict[str, Any]:
        return {
            "data": {
                "teams": {
                    "nodes": [{"id": "team_ENG", "key": "ENG", "name": "Engineering"}]
                },
                "viewer": {"organization": {"id": "org_1"}},
            }
        }

    monkeypatch.setattr(plc, "graphql", fake_graphql)
    result = plc.probe_team_scope(tmp_path, cfg, token="lin_test_token_not_real")
    assert result["verdict"] == "ok"
    assert result["teamId"] == "team_ENG"
    assert result["teamKey"] == "ENG"

    overscoped = plc.detect_overscoped_key(
        {
            "data": {
                "teams": {
                    "nodes": [
                        {"id": "team_ENG", "key": "ENG"},
                        {"id": "team_OTHER", "key": "OPS"},
                    ]
                }
            }
        },
        expected_team_id="team_ENG",
        expected_team_key="ENG",
    )
    assert overscoped is True


def test_r13_dual_budget_tracks_count_and_complexity(tmp_git_repo: Path) -> None:
    """R13 — request-count and complexity points tracked; github/jira remain count-only compatible."""
    ledger = prb.RequestBudgetLedger.from_config(tmp_git_repo, "linear")
    assert ledger.max_calls >= 1
    assert ledger.max_complexity_points >= 1
    ledger.charge("probe", count=1, complexity=120)
    snap = ledger.snapshot()
    assert snap["totalCharged"] == 1
    assert snap["totalComplexityCharged"] == 120
    assert snap.get("countsOnly") is False
    assert snap["schemaVersion"] >= 2

    gh = prb.RequestBudgetLedger.from_config(tmp_git_repo, "github-issues")
    gh.charge("search", count=1)
    gh_snap = gh.snapshot()
    assert gh_snap["totalCharged"] == 1
    assert gh_snap.get("countsOnly") is True


def test_r13_ratelimited_graphql_extension_handled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R13 — GraphQL extensions.code RATELIMITED raises typed rate-limit error (not only HTTP 429)."""
    cfg = _cfg()
    monkeypatch.setenv("ISSUES_LINEAR_TOKEN", "lin_test_token_not_real")

    def fake_http(*_a: Any, **_k: Any) -> tuple[int, dict[str, str], str]:
        body = json.dumps(
            {
                "errors": [
                    {
                        "message": "rate limited",
                        "extensions": {"code": "RATELIMITED"},
                    }
                ]
            }
        )
        return 200, {}, body

    monkeypatch.setattr(issues_http, "http_request", fake_http)
    with pytest.raises(plc.LinearRateLimited) as exc:
        plc.graphql(tmp_path, cfg, query="{ viewer { id } }", variables=None)
    assert "RATELIMITED" in str(exc.value).upper() or exc.value.code == "RATELIMITED"
    assert "lin_test_token_not_real" not in str(exc.value)


def test_r13_complexity_aware_query_planner_splits() -> None:
    """R13 — planner splits work units under per-query complexity cap."""
    units = [{"id": f"u{i}", "estimate": 3000} for i in range(5)]
    batches = prb.plan_queries_under_complexity_cap(units, max_complexity=10000)
    assert len(batches) >= 2
    for batch in batches:
        assert sum(u["estimate"] for u in batch) <= 10000


def test_r14_bare_issues_array_batch_footgun_blocked() -> None:
    """R14 — bare issues array path rejected; wrapper shape required."""
    with pytest.raises(plc.LinearBatchInputError) as exc:
        plc.validate_batch_create_input([{"title": "a", "teamId": "t1"}])
    assert exc.value.code == "bare-issues-array"

    ok = plc.validate_batch_create_input({"issues": [{"title": "a", "teamId": "t1"}]})
    assert ok["issues"][0]["title"] == "a"

    with pytest.raises(plc.LinearBatchInputError):
        plc.create_issue_batch_payload([{"title": "x", "teamId": "t1"}])

    payload = plc.create_issue_batch_payload({"issues": [{"title": "x", "teamId": "t1"}]})
    assert "issues" in payload["variables"]["input"]
    assert isinstance(payload["variables"]["input"]["issues"], list)


def test_r23_oauth_auth_mode_header_only() -> None:
    """R23 — authMode oauth changes token acquisition/header only; verbs unchanged."""
    api_headers = plc.auth_headers("key_abc", auth_mode="api-key")
    assert api_headers["Authorization"] == "key_abc"
    assert not api_headers["Authorization"].startswith("Bearer ")

    oauth_headers = plc.auth_headers("access_tok", auth_mode="oauth")
    assert oauth_headers["Authorization"] == "Bearer access_tok"

    verbs_api = plc.adapter_verbs()
    verbs_oauth = plc.adapter_verbs(auth_mode="oauth")
    assert verbs_api == verbs_oauth

    guidance = plc.oauth_token_storage_guidance()
    assert guidance["operatorLocalOnly"] is True
    assert guidance["mustNotCommitToPlanningRepo"] is True


def test_r23_doctor_refuses_shared_ci_oauth_without_exception(
    tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R23 — doctor refuses authMode oauth via shared CI secret absent exception."""
    monkeypatch.setenv("CI", "true")
    monkeypatch.setenv("ISSUES_LINEAR_TOKEN", "oauth-access-from-ci")
    cfg_path = tmp_git_repo / ".cursor" / "workflow.config.json"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(_cfg(auth_mode="oauth")), encoding="utf-8")

    finding = plc.doctor_oauth_ci_secret_check(tmp_git_repo)
    assert finding["verdict"] == "fail"
    assert finding["error"] == "oauth-shared-ci-secret-refused"

    cfg_ok = _cfg(auth_mode="oauth", oauth_shared_ci_exception=True)
    cfg_path.write_text(json.dumps(cfg_ok), encoding="utf-8")
    finding_ok = plc.doctor_oauth_ci_secret_check(tmp_git_repo)
    assert finding_ok["verdict"] == "ok"
    assert finding_ok.get("exceptionPath") is True
