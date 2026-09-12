"""PRD 339 R33 — Linear PRD/Brainstorm/Gap projection rebuild and drift correction."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_projection as plp
import planning_store as ps


def _semantic_records() -> list[dict[str, Any]]:
    return [
        {
            "unitId": "339-prd-demo",
            "artifactType": "prd",
            "title": "Planning store expansion",
            "status": "in_flight",
            "content": "---\nid: 339-prd-demo\ntype: prd\nstatus: in_flight\n---\n# Planning store expansion\n\nShip Linear projection rebuild.",
            "links": ["https://linear.app/example/project/demo"],
        },
        {
            "unitId": "339-bs-demo",
            "artifactType": "brainstorm",
            "prdUnitId": "339-prd-demo",
            "title": "Brainstorm options",
            "status": "proposed",
            "content": "# Brainstorm options\n\nExplore provider adapters.",
        },
        {
            "unitId": "gap-339-demo",
            "artifactType": "gap",
            "prdUnitId": "339-prd-demo",
            "title": "Projection drift repair",
            "status": "open",
            "lifecycle": "open",
            "prerequisites": ["gap-338-prerequisite"],
            "absorbs": ["339-prd-demo"],
            "content": "# Projection drift repair\n",
        },
    ]


def test_prd_project_spec_has_status_summary_links_and_marker() -> None:
    record = _semantic_records()[0]
    spec = plp.build_prd_project_spec(record, project_key="demo")
    assert spec["verdict"] == "pass"
    assert spec["linearEntity"] == "Project"
    assert spec["marker"] == "sw:unit:339-prd-demo"
    owned = spec["ownedFields"]
    assert owned["status"] == "in_flight"
    assert owned["requirementsSummary"]
    assert owned["links"] == ["https://linear.app/example/project/demo"]
    assert spec["isFreezeAuthority"] is False
    assert spec["isSourceOfTruth"] is False


def test_brainstorm_document_spec_links_parent_project() -> None:
    record = _semantic_records()[1]
    spec = plp.build_brainstorm_document_spec(
        record,
        project_key="demo",
        prd_project_entity_id="proj-demo",
    )
    assert spec["verdict"] == "pass"
    assert spec["linearEntity"] == "Document"
    assert spec["attachedToProject"] == "proj-demo"
    assert spec["ownedFields"]["prdUnitId"] == "339-prd-demo"
    assert spec["isSourceOfTruth"] is False


def test_gap_issue_spec_has_lifecycle_prereq_absorption_and_gap_label() -> None:
    record = _semantic_records()[2]
    spec = plp.build_gap_issue_spec(
        record,
        project_key="demo",
        prd_project_entity_id="proj-demo",
    )
    assert spec["verdict"] == "pass"
    assert spec["linearEntity"] == "Issue"
    assert spec["projectMembership"] == "proj-demo"
    owned = spec["ownedFields"]
    assert owned["lifecycle"] == "open"
    assert owned["prerequisites"] == ["gap-338-prerequisite"]
    assert owned["absorbs"] == ["339-prd-demo"]
    assert "Gap" in spec["labels"]


def test_linear_projection_rebuild_from_semantic_store(
    tmp_path: Path,
) -> None:
    """R33 — reconstruct missing entities, repair drift, preserve semantic-store authority."""
    store = plp.LinearProjectionRebuildStore()
    first = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        _semantic_records(),
        project_key="demo",
        store=store,
    )
    assert first["verdict"] == "pass", first
    assert first["semanticAuthority"] is True
    assert first["freezeAuthority"] == "portable-graph"
    assert first["created"] == 3
    assert first["counts"] == {"Project": 1, "Document": 1, "Milestone": 0, "Issue": 1}

    prd_lookup = ps.projection_ledger_lookup(
        tmp_path,
        unit_id="339-prd-demo",
        artifact_type="prd",
        provider="linear",
    )
    assert prd_lookup["verdict"] == "pass"
    prd_entity_id = prd_lookup["entry"]["entityId"]

    doc = store.find_by_marker("sw:unit:339-bs-demo", "Document")
    assert doc is not None
    assert doc["attachedToProject"] == prd_entity_id

    gap = store.find_by_marker("sw:unit:gap-339-demo", "Issue")
    assert gap is not None
    assert gap["projectMembership"] == prd_entity_id
    assert "Gap" in gap.get("labels", [])

    # Idempotent second rebuild — no duplicate entities.
    second = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        _semantic_records(),
        project_key="demo",
        store=store,
    )
    assert second["verdict"] == "pass"
    assert second["created"] == 0
    assert second["counts"] == {"Project": 1, "Document": 1, "Milestone": 0, "Issue": 1}

    # Drift without overwrite halts (semantic store remains authority).
    drifted = list(_semantic_records())
    drifted[0] = {**drifted[0], "status": "done"}
    ps.projection_ledger_upsert(
        tmp_path,
        unit_id="339-prd-demo",
        artifact_type="prd",
        provider="linear",
        entity_id=prd_entity_id,
        owned_fields={"title": "Human edited", "status": "in_flight", "marker": "sw:unit:339-prd-demo"},
        marker="sw:unit:339-prd-demo",
    )
    blocked = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        drifted,
        project_key="demo",
        store=store,
        overwrite_drift=False,
    )
    assert blocked["verdict"] == "fail"
    assert blocked["error"] == "projection_drift"

    repaired = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        drifted,
        project_key="demo",
        store=store,
        overwrite_drift=True,
    )
    assert repaired["verdict"] == "pass"
    assert repaired["repaired"] >= 1
    prd = store.find_by_marker("sw:unit:339-prd-demo", "Project")
    assert prd is not None
    assert prd["ownedFields"]["status"] == "done"
    assert prd["isFreezeAuthority"] is False


def test_rebuild_projection_for_unit_idempotent() -> None:
    graph = {
        "freezeAuthority": "portable-graph",
        "units": [
            {
                "unitId": "339-prd-demo",
                "artifactType": "prd",
                "entityId": "proj-1",
                "ownedFields": {"title": "Demo", "status": "in_flight"},
                "marker": "sw:unit:339-prd-demo",
            }
        ],
    }
    first = plp.rebuild_projection_for_unit(graph, unit_id="339-prd-demo")
    second = plp.rebuild_projection_for_unit(graph, unit_id="339-prd-demo")
    assert first["verdict"] == "pass"
    assert second["verdict"] == "pass"
    assert first["idempotent"] is True
    assert second["duplicateEntities"] is False
