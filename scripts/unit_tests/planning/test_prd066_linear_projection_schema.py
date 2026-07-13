"""PRD 066 phase 5 — Linear projection schema fixture assertions (R6, R7, R8, R29)."""

from __future__ import annotations

import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_store as ps


def _fixture_graph() -> dict:
    return {
        "freezeAuthority": "portable-graph",
        "units": [
            {
                "unitId": "066-prd",
                "artifactType": "prd",
                "entityId": "lin-proj-1",
                "ownedFields": {"title": "PRD 066", "status": "in_flight"},
                "marker": "sw:unit:066-prd",
            },
            {
                "unitId": "066-bs",
                "artifactType": "brainstorm",
                "entityId": "lin-doc-1",
                "prdUnitId": "066-prd",
                "ownedFields": {"title": "Brainstorm"},
                "marker": "sw:unit:066-bs",
            },
            {
                "unitId": "gap-079",
                "artifactType": "gap",
                "entityId": "lin-iss-gap",
                "prdUnitId": "066-prd",
                "ownedFields": {"title": "gap-079"},
                "marker": "sw:unit:gap-079",
            },
            {
                "unitId": "066-phase-5",
                "artifactType": "phase",
                "entityId": "lin-ms-5",
                "prdUnitId": "066-prd",
                "ownedFields": {"title": "Phase 5"},
                "marker": "sw:unit:066-phase-5",
            },
            {
                "unitId": "066-task-5.1",
                "artifactType": "task",
                "entityId": "lin-iss-task",
                "phaseUnitId": "066-phase-5",
                "ownedFields": {"title": "Map entities", "status": "backlog"},
                "marker": "sw:unit:066-task-5.1",
            },
            {
                "unitId": "program-066",
                "artifactType": "program",
                "entityId": "lin-init-1",
                "ownedFields": {"title": "Planning store wave"},
            },
            {
                "unitId": "wave-066",
                "artifactType": "cycle-wave",
                "entityId": "lin-cycle-1",
                "ownedFields": {"title": "Wave A"},
            },
        ],
        "edges": [
            {
                "type": "absorbs",
                "sourceType": "gap",
                "sourceId": "gap-079",
                "targetType": "prd",
                "targetId": "066-prd",
            },
            {
                "type": "feeds",
                "sourceType": "brainstorm",
                "sourceId": "066-bs",
                "targetType": "prd",
                "targetId": "066-prd",
            },
            {
                "type": "depends",
                "sourceType": "task",
                "sourceId": "066-task-5.1",
                "targetType": "gap",
                "targetId": "gap-079",
            },
        ],
    }


def test_r6_entity_mapping_prd_document_gap_milestone_issue() -> None:
    """R6 — PRD→Project, Brainstorm→Document, Gap→Issue, phases→Milestones, tasks→Issues."""
    mapping = ps.linear_entity_mapping()
    by_type = mapping["byArtifactType"]
    assert by_type["prd"]["linearEntity"] == "Project"
    assert by_type["brainstorm"]["linearEntity"] == "Document"
    assert by_type["gap"]["linearEntity"] == "Issue"
    assert "Gap" in by_type["gap"]["labels"]
    assert by_type["phase"]["linearEntity"] == "Milestone"
    assert by_type["task"]["linearEntity"] == "Issue"
    assert by_type["task"]["milestoneMembership"] is True
    assert by_type["program"]["linearEntity"] == "Initiative"
    assert by_type["cycle-wave"]["linearEntity"] == "Cycle"

    layout = ps.project_graph_to_linear_layout(_fixture_graph())
    assert layout["verdict"] == "pass"
    assert layout["freezeAuthority"] == "portable-graph"
    assert layout["isSourceOfTruth"] is False
    counts = layout["counts"]
    assert counts.get("Project") == 1
    assert counts.get("Document") == 1
    assert counts.get("Milestone") == 1
    assert counts.get("Initiative") == 1
    assert counts.get("Cycle") == 1
    # Gap + task both Issues
    assert counts.get("Issue") == 2
    gap = next(e for e in layout["entities"] if e["artifactType"] == "gap")
    assert gap["labels"] == ["Gap"]
    assert gap["projectMembership"] == "066-prd"
    task = next(e for e in layout["entities"] if e["artifactType"] == "task")
    assert task["milestoneId"] == "066-phase-5"


def test_r7_initiative_probe_and_substitute_views() -> None:
    """R7 — missing Initiative → matrix degradation + documented substitute; silent skip prohibited."""
    available = ps.probe_initiative_availability(workspace={"initiativesEnabled": True})
    assert available["available"] is True
    assert available["degraded"] is False

    missing = ps.probe_initiative_availability(workspace={"initiativesEnabled": False})
    assert missing["available"] is False
    assert missing["degraded"] is True

    applied = ps.apply_initiative_capability(
        ps.operator_projection_capability_matrix(),
        probe=missing,
        substitute_configured=True,
    )
    assert applied["verdict"] == "ok"
    assert applied["initiativeAvailable"] is False
    assert applied["silentSkipProhibited"] is True
    assert applied["r14Answerable"] is True
    assert applied["degradationNotices"]
    notice = applied["degradationNotices"][0]
    assert notice["concept"] == "initiative"
    assert notice["silentSkip"] is False
    assert notice["fallbackBrowsePath"]
    assert applied["substituteViews"]["requiredViews"]

    fail_closed = ps.apply_initiative_capability(
        probe=missing,
        substitute_configured=False,
    )
    assert fail_closed["verdict"] == "fail"
    assert fail_closed["error"] == "initiative-unavailable-without-substitute"


def test_r8_cycles_orthogonal_to_milestones_and_share_notice() -> None:
    """R8 — Cycle assign preserves Milestone; no Cycle def mutation; loud shared-cadence notice."""
    issue = {"id": "lin-iss-task", "milestoneId": "lin-ms-5"}
    assigned = ps.assign_issue_to_cycle(issue, cycle_id="lin-cycle-1")
    assert assigned["verdict"] == "pass"
    assert assigned["issue"]["cycleId"] == "lin-cycle-1"
    assert assigned["issue"]["milestoneId"] == "lin-ms-5"
    assert assigned["mutatedCycleDefinition"] is False
    assert assigned["milestonePreserved"] is True

    refused = ps.assign_issue_to_cycle(
        issue, cycle_id="lin-cycle-1", mutate_cycle_definition=True
    )
    assert refused["verdict"] == "fail"
    assert refused["error"] == "cycle-definition-mutation-prohibited"

    dropped = ps.assert_cycle_orthogonal_to_milestone(
        issue={"id": "x", "cycleId": "c1"},
        cycle_id="c1",
        milestone_id="ms-1",
    )
    assert dropped["verdict"] == "fail"
    assert dropped["error"] == "cycle-assignment-dropped-milestone"

    quiet = ps.cycle_sharing_notice(team_has_active_human_cycle=False)
    assert quiet["loud"] is False
    loud = ps.cycle_sharing_notice(team_has_active_human_cycle=True)
    assert loud["loud"] is True
    assert loud["sharedCadence"] is True
    assert loud["notice"]["code"] == "shared-cycle-cadence"
    assert loud["notice"]["mutatesCycleDefinition"] is False
    assert loud["notice"]["phaseSourceOfTruth"] == "Milestone"


def test_r29_endpoint_typed_edge_encoding() -> None:
    """R29 — absorbs/feeds without IssueRelation to Project/Document; no stub Issues."""
    absorbs = ps.encode_planning_edge(
        {
            "type": "absorbs",
            "sourceType": "gap",
            "sourceId": "gap-079",
            "targetType": "prd",
            "targetId": "066-prd",
        }
    )
    assert absorbs["verdict"] == "pass"
    assert absorbs["encoding"] == "project-membership+gap-label"
    assert absorbs["issueRelation"] is False

    feeds = ps.encode_planning_edge(
        {
            "type": "feeds",
            "sourceType": "brainstorm",
            "sourceId": "066-bs",
            "targetType": "prd",
            "targetId": "066-prd",
        }
    )
    assert feeds["verdict"] == "pass"
    assert feeds["encoding"] == "document-attachment+project-metadata"
    assert feeds["issueRelation"] is False

    depends = ps.encode_planning_edge(
        {
            "type": "depends",
            "sourceType": "task",
            "sourceId": "t1",
            "targetType": "gap",
            "targetId": "g1",
        }
    )
    assert depends["verdict"] == "pass"
    assert depends["issueRelation"] is True

    banned = ps.encode_planning_edge(
        {
            "type": "feeds",
            "sourceType": "brainstorm",
            "sourceId": "066-bs",
            "targetType": "prd",
            "targetId": "066-prd",
            "useIssueRelation": True,
            "sourceEntity": "Document",
            "targetEntity": "Project",
        }
    )
    assert banned["verdict"] == "fail"
    assert banned["error"] == "issue-relation-to-project-or-document"

    stub = ps.encode_planning_edge(
        {
            "type": "feeds",
            "sourceType": "brainstorm",
            "sourceId": "066-bs",
            "targetType": "prd",
            "targetId": "066-prd",
            "stubIssueEndpoints": True,
        }
    )
    assert stub["verdict"] == "fail"
    assert stub["error"] == "stub-issue-endpoints-prohibited"

    layout = ps.project_graph_to_linear_layout(_fixture_graph())
    assert layout["verdict"] == "pass"
    assert all(e["issueRelation"] is False for e in layout["edges"] if e["edgeType"] in {"absorbs", "feeds"})
    assert any(e["edgeType"] == "depends" and e["issueRelation"] for e in layout["edges"])


def test_linear_projection_schema_contract_surface() -> None:
    """Facade contract exposes R6–R8/R29 schema summary."""
    contract = ps.linear_projection_schema_contract()
    assert contract["verdict"] == "ok"
    assert contract["entityMapping"]["verdict"] == "ok"
    assert "absorbs" in contract["edgeEncodings"]
    assert contract["cycleOrthogonality"]["orthogonalTo"] == "Milestone"
    assert contract["r14SubstituteViews"]["silentSkipProhibited"] is True
