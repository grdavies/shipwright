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
from planning_notion_projection import (
    NOTION_ENTITY_MAP,
    apply_dual_property_capability,
    encode_planning_edge,
    map_artifact_to_notion_entity,
    project_graph_to_notion_layout,
    rebuild_projection_for_unit,
    resolve_canonical_freeze_body,
)


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


def test_notion_recognized_and_shipped() -> None:
    assert "notion" in ps.ISSUES_PROVIDERS
    assert "notion" in ps.SHIPPED_ISSUES_PROVIDERS


def test_registration_footprint_notion_surface() -> None:
    footprint = ps.issues_provider_registration_footprint()
    assert footprint["notion"]["liveClientWired"] is True
    assert footprint["notion"]["promotionGatedBy"] == ["conformance", "docs-gate"]
    assert footprint["rateLimitMap"]["notion"] == "notion"
    assert footprint["capabilityIndexIds"]["notion"] == "provider.providers.issues.notion"
    assert footprint["recognitionVsShipped"]["notion"] == {
        "recognized": True,
        "shipped": True,
        "deferred": False,
    }


def test_doctor_notion_shipped_passes(tmp_path: Path) -> None:
    result = ps.doctor_issues_provider_stub(tmp_path, _notion_cfg())
    assert result["verdict"] == "pass"
    assert result["provider"] == "notion"
    assert "notice" not in result


def test_doctor_notion_stub_refused_when_client_unwired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(notion_provider, "live_client_wired", lambda: False)
    result = notion_provider.doctor_stub_result(
        tmp_path,
        provider="notion",
        issues_providers=frozenset({"github-issues"}),
        shipped_providers=ps.SHIPPED_ISSUES_PROVIDERS,
    )
    assert result is not None
    assert result["verdict"] == "fail"
    assert result["error"] == "notion-stub-refused"


def test_issues_lib_notion_shipped_fixture_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    client = issues_lib.IssuesClient(tmp_path, "notion")
    backend = client._live_backend()
    assert backend is not None


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

# --- PRD 327 phase 3 operator projection (R5) ---


def _fixture_graph() -> dict:
    return {
        "units": [
            {"unitId": "prd-1", "artifactType": "prd"},
            {"unitId": "bs-1", "artifactType": "brainstorm", "prdUnitId": "prd-1"},
            {"unitId": "gap-1", "artifactType": "gap", "prdUnitId": "prd-1"},
            {"unitId": "phase-1", "artifactType": "phase", "prdUnitId": "prd-1"},
            {"unitId": "task-1", "artifactType": "task"},
            {"unitId": "task-2", "artifactType": "task"},
            {"unitId": "prog-1", "artifactType": "program"},
            {"unitId": "prog-status", "artifactType": "progress"},
        ],
        "edges": [
            {
                "edgeType": "absorbs",
                "source": {"unitId": "gap-1", "kind": "gap"},
                "target": {"unitId": "prd-1", "kind": "prd"},
            },
            {
                "edgeType": "feeds",
                "source": {"unitId": "bs-1", "kind": "brainstorm"},
                "target": {"unitId": "prd-1", "kind": "prd"},
            },
            {
                "edgeType": "depends",
                "source": {"unitId": "task-2", "kind": "task"},
                "target": {"unitId": "task-1", "kind": "task"},
            },
        ],
    }


def test_notion_entity_map_covers_required_artifact_types() -> None:
    required = {"prd", "brainstorm", "gap", "phase", "task", "program", "progress"}
    assert required <= set(NOTION_ENTITY_MAP)
    assert NOTION_ENTITY_MAP["prd"]["notionEntity"] == "DatabasePage"
    assert NOTION_ENTITY_MAP["progress"]["property"] == "Status"
    assert NOTION_ENTITY_MAP["program"]["property"] == "select"
    assert NOTION_ENTITY_MAP["phase"]["windowProperty"] == "date"


def test_map_artifact_refuses_unknown_type() -> None:
    bad = map_artifact_to_notion_entity("wiki")
    assert bad["verdict"] == "fail"
    assert bad["error"] == "unsupported-artifact-type"


def test_project_graph_to_notion_layout_portable_graph_authority() -> None:
    layout = project_graph_to_notion_layout(_fixture_graph())
    assert layout["verdict"] == "pass"
    assert layout["freezeAuthority"] == "portable-graph"
    assert layout["isSourceOfTruth"] is False
    assert layout["properties"]["completion"] == "Status"
    roles = set(layout["byDatabaseRole"])
    assert {"prd", "brainstorm", "gap", "phase", "task", "program", "progress"} <= roles
    encodings = {e["edgeType"]: e["encoding"] for e in layout["edges"]}
    assert encodings["absorbs"] == "dual_property"
    assert encodings["feeds"] == "dual_property"
    assert encodings["depends"] == "task-task-relation"


def test_dual_property_degrades_with_operator_notice() -> None:
    layout = project_graph_to_notion_layout(
        _fixture_graph(),
        workspace={"dualPropertyEnabled": False},
    )
    assert layout["verdict"] == "pass"
    absorbs = next(e for e in layout["edges"] if e["edgeType"] == "absorbs")
    assert absorbs["encoding"] == "single_property+back-reference-view"
    assert absorbs["degradationNotices"]
    assert absorbs["degradationNotices"][0]["silentSkip"] is False
    cap = apply_dual_property_capability(
        probe={"available": False},
        substitute_configured=True,
    )
    assert cap["verdict"] == "ok"
    assert cap["dualPropertyAvailable"] is False
    assert cap["substituteViews"]["requiredViews"]


def test_stub_page_endpoints_prohibited() -> None:
    edge = encode_planning_edge(
        {
            "edgeType": "absorbs",
            "source": {"unitId": "gap-1", "kind": "gap", "stub": True},
            "target": {"unitId": "prd-1", "kind": "prd"},
        }
    )
    assert edge["verdict"] == "fail"
    assert edge["error"] == "stub-page-endpoints-prohibited"


def test_projection_prefer_split_brain_and_drift() -> None:
    prefer = resolve_canonical_freeze_body(
        unit_id="prd-1",
        body="# body",
        prefer="projection",
    )
    assert prefer["verdict"] == "fail"
    assert prefer["error"] == "projection-prefer-split-brain"

    drift = resolve_canonical_freeze_body(
        unit_id="prd-1",
        body="# canonical",
        projection_mirrors=[
            {
                "entityKind": "DatabasePage",
                "entityId": "page-1",
                "body": "# other",
                "derived": False,
                "bodyParityRequired": True,
                "isFreezeAuthority": False,
            }
        ],
    )
    assert drift["verdict"] == "fail"
    assert drift["error"] == "canonical-projection-body-drift"


def test_rebuild_projection_idempotent_no_duplicates() -> None:
    graph = _fixture_graph()
    first = rebuild_projection_for_unit(graph, unit_id="prd-1")
    second = rebuild_projection_for_unit(graph, unit_id="prd-1")
    assert first["verdict"] == "pass"
    assert second["verdict"] == "pass"
    assert first["idempotent"] is True
    assert second["duplicatePages"] is False


def test_facade_notion_projection_schema_contract() -> None:
    contract = ps.notion_projection_schema_contract()
    assert contract["verdict"] == "ok"
    assert contract["action"] == "notion-projection-schema-contract"
    assert "prd" in contract["entityMapping"]["byArtifactType"]
    assert contract["parityMatrixRow"]["edges"] == "dual_property relations"
    matrix = ps.operator_projection_capability_matrix()
    assert "notion" in matrix["backends"]
    notion_prd = next(r for r in matrix["rows"] if r["row"] == "prd")
    assert notion_prd["notion"] == "prd-database-page"


def test_facade_project_graph_to_notion_layout() -> None:
    layout = ps.project_graph_to_notion_layout(_fixture_graph())
    assert layout["verdict"] == "pass"
    assert layout["provider"] == "notion"


# --- PRD 327 phase 5 docs, conformance, shipped gate (R12/R13) ---


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_notion_docs_gate_passes() -> None:
    root = _repo_root()
    result = pnc.docs_gate(root)
    assert result["verdict"] == "ok"
    assert result["gate"] == "docs-gate"


def test_notion_promotion_gate_evidence_green() -> None:
    root = _repo_root()
    evidence = pnc.notion_promotion_gate_evidence(root)
    assert evidence["verdict"] == "ok", evidence.get("failures")


def test_notion_conformance_record_matches_live() -> None:
    from _planning_pkg_loader import load_submodule

    pc = load_submodule("provider_conformance")
    root = _repo_root()
    evidence = pc.conformance_evidence(root, "notion")
    assert evidence["verdict"] == "ok", evidence.get("failures")

