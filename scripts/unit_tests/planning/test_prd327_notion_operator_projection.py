"""PRD 327 phase 3 — Notion operator projection schema (R5)."""

from __future__ import annotations

import planning_store as ps
from planning_notion_projection import (
    NOTION_ENTITY_MAP,
    apply_dual_property_capability,
    encode_planning_edge,
    map_artifact_to_notion_entity,
    project_graph_to_notion_layout,
    rebuild_projection_for_unit,
    resolve_canonical_freeze_body,
)


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
