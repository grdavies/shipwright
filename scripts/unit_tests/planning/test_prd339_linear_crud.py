"""PRD 339 R33 — Linear GraphQL pagination, semantic CRUD, canonicalization, failures."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import issues_lib
import planning_canonical as pc
import planning_linear_client as plc
import planning_store_facade as psf
from planning.backends.linear import LinearSemanticCrud, wire_linear_semantic_crud


def _cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "linear",
                "projectKey": "demo",
                "issues": {
                    "tokenEnv": "ISSUES_LINEAR_TOKEN",
                    "authMode": "api-key",
                    "teamKey": "ENG",
                    "teamId": "team_ENG",
                },
            }
        }
    }


def _fixture_client(tmp_path: Path) -> plc.LinearIssuesClient:
    store = issues_lib.FixtureIssuesStore(tmp_path / "linear-crud-fixture.json")
    return plc.LinearIssuesClient(tmp_path, cfg=_cfg(), fixture_store=store)


def _semantic(tmp_path: Path) -> LinearSemanticCrud:
    client = _fixture_client(tmp_path)
    return wire_linear_semantic_crud(tmp_path, _cfg(), client=client)


def _issue_node(issue_id: str, *, identifier: str, unit_id: str, artifact_type: str = "gap") -> dict[str, Any]:
    body = (
        f"<!-- {pc.MARKER_UNIT_ID}: {unit_id} -->\n"
        f"<!-- {pc.MARKER_ARTIFACT_TYPE}: {artifact_type} -->\n"
        f"# Gap {unit_id}\n"
    )
    return {
        "id": issue_id,
        "identifier": identifier,
        "title": f"[demo] {artifact_type}:{unit_id}",
        "description": body,
        "updatedAt": "2026-01-01T00:00:00.000Z",
        "state": {"id": "state_open", "name": "Todo", "type": "unstarted"},
        "labels": {
            "nodes": [
                {"id": "lbl_project", "name": "sw:project:demo"},
                {"id": "lbl_type", "name": f"sw:{artifact_type}"},
                {"id": "lbl_unit", "name": f"sw:unit:{unit_id}"},
            ]
        },
        "comments": {"nodes": []},
        "relations": {"nodes": []},
        "inverseRelations": {"nodes": []},
    }


def test_graphql_pagination_one_page(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R33 — single-page search returns all nodes without extra requests."""
    client = _fixture_client(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        calls.append(dict(variables or {}))
        return {
            "data": {
                "issues": {
                    "nodes": [_issue_node("issue_1", identifier="ENG-1", unit_id="gap-001")],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

    monkeypatch.setattr(client, "_gql", fake_gql)
    nodes = client._paginated_issue_nodes({"labels": {"name": {"in": ["sw:project:demo"]}}})
    assert len(nodes) == 1
    assert len(calls) == 1
    assert calls[0].get("after") is None


def test_graphql_pagination_many_pages(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R33 — bounded pagination walks cursors until hasNextPage is false."""
    client = _fixture_client(tmp_path)
    calls: list[dict[str, Any]] = []

    def fake_gql(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        variables = dict(variables or {})
        calls.append(variables)
        after = variables.get("after")
        if after is None:
            return {
                "data": {
                    "issues": {
                        "nodes": [_issue_node("issue_1", identifier="ENG-1", unit_id="gap-001")],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cursor_1"},
                    }
                }
            }
        return {
            "data": {
                "issues": {
                    "nodes": [_issue_node("issue_2", identifier="ENG-2", unit_id="gap-002")],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }

    monkeypatch.setattr(client, "_gql", fake_gql)
    nodes = client._paginated_issue_nodes({"labels": {"name": {"in": ["sw:project:demo"]}}})
    assert len(nodes) == 2
    assert len(calls) == 2
    assert calls[1].get("after") == "cursor_1"


def test_semantic_create_get_canonical_round_trip(tmp_path: Path) -> None:
    """R33 — semantic CRUD preserves unit id, artifact type, labels, and body hash."""
    semantic = _semantic(tmp_path)
    content = "---\ntype: gap\nstatus: proposed\n---\n\n# Gap body\n"
    created = semantic.create(unit_id="gap-339", body_path="docs/planning/gap-339/body.md", content=content)
    assert created["verdict"] == "ok"
    assert created["unitId"] == "gap-339"
    assert created["artifactType"] == "gap"
    assert "sw:project:demo" in created["labels"]
    assert created["bodyHash"]

    fetched = semantic.get(str(created["issueId"]), unit_id="gap-339", body_path="docs/planning/gap-339/body.md")
    assert fetched["unitId"] == "gap-339"
    assert fetched["bodyHash"] == created["bodyHash"]
    assert fetched["canonicalHash"] == created["canonicalHash"]


def test_idempotent_update_with_matching_etag(tmp_path: Path) -> None:
    """R33 — update with unchanged etag/content is idempotent."""
    semantic = _semantic(tmp_path)
    content = "# Stable body\n"
    created = semantic.create(unit_id="gap-idem", body_path="docs/planning/gap-idem/body.md", content=content)
    updated = semantic.update(
        str(created["issueId"]),
        unit_id="gap-idem",
        body_path="docs/planning/gap-idem/body.md",
        if_match=str(created["etag"]),
    )
    assert updated.get("idempotent") is True
    assert updated["etag"] == created["etag"]


def test_rate_limit_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R33 — bounded retry on RATELIMITED then success."""
    attempts = {"count": 0}

    def fake_once(*_a: Any, **_k: Any) -> dict[str, Any]:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise plc.LinearRateLimited("rate limited")
        return {"data": {"viewer": {"id": "viewer_1"}}}

    monkeypatch.setattr(plc, "_graphql_once", fake_once)
    monkeypatch.setattr(plc.time, "sleep", lambda _s: None)
    payload = plc.graphql(tmp_path, _cfg(), query="query { viewer { id } }", token="test-token")
    assert payload["data"]["viewer"]["id"] == "viewer_1"
    assert attempts["count"] == 2


def test_auth_denial_normalized() -> None:
    """R33 — HTTP/GraphQL auth failures normalize to auth-denied."""
    payload = {"errors": [{"message": "Unauthorized", "extensions": {"code": "FORBIDDEN"}}]}
    with pytest.raises(plc.LinearGraphQLAuthError) as exc_info:
        plc.normalize_graphql_errors(payload, http_status=200)
    assert exc_info.value.code == "auth-denied"


def test_scope_failure_normalized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R33 — scope failures normalize to scope-failure."""
    payload = {
        "data": {
            "teams": {
                "nodes": [
                    {"id": "team_ENG", "key": "ENG"},
                    {"id": "team_OPS", "key": "OPS"},
                ]
            }
        }
    }

    monkeypatch.setattr(plc, "graphql", lambda *_a, **_k: payload)
    result = plc.probe_team_scope(tmp_path, _cfg(), token="test-token")
    assert result["verdict"] == "fail"
    assert result["error"] == "overscoped-key"


def test_malformed_response_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """R33 — malformed JSON/payload surfaces typed client errors."""
    monkeypatch.setattr(
        plc,
        "_graphql_once",
        lambda *_a, **_k: (_ for _ in ()).throw(plc.LinearClientError("invalid JSON response", code="invalid-json")),
    )
    with pytest.raises(plc.LinearClientError) as exc_info:
        plc.graphql(tmp_path, _cfg(), query="query { viewer { id } }", token="test-token")
    assert exc_info.value.code == "invalid-json"


def test_facade_wire_linear_semantic_crud(tmp_path: Path) -> None:
    """R33 — facade wires semantic CRUD registration and operations."""
    footprint = psf._linear_semantic_crud_registration()
    assert footprint["backendId"] == "linear-semantic"
    assert "create" in footprint["verbs"]

    client = _fixture_client(tmp_path)
    out = psf.linear_semantic_crud(
        tmp_path,
        operation="create",
        unit_id="gap-facade",
        body_path="docs/planning/gap-facade/body.md",
        content="# Facade path\n",
        client=client,
    )
    assert out["verdict"] == "ok"
    search = psf.linear_semantic_crud(
        tmp_path,
        operation="search",
        unit_id="gap-facade",
        client=client,
    )
    assert search["verdict"] == "ok"
    assert len(search["matches"]) == 1


def test_normalize_graphql_errors_missing_data() -> None:
    """R33 — missing data with no errors is invalid-payload."""
    with pytest.raises(plc.LinearClientError) as exc_info:
        plc.normalize_graphql_errors({"errors": []}, http_status=200)
    assert exc_info.value.code == "invalid-payload"
