"""PRD 339 R33 — Linear phase milestones, task sub-issues, and resumable hierarchy rebuild."""

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
import planning_store_facade as facade


def _prd_record() -> dict[str, Any]:
    return {
        "unitId": "339-prd-hierarchy",
        "artifactType": "prd",
        "title": "Hierarchy rebuild",
        "status": "in_flight",
        "content": "# Hierarchy rebuild\n",
    }


def _phase_record(phase_id: str, *, depends_on: list[str] | None = None, status: str = "backlog") -> dict[str, Any]:
    unit_id = f"339-phase-{phase_id}"
    return {
        "unitId": unit_id,
        "artifactType": "phase",
        "phaseId": phase_id,
        "prdUnitId": "339-prd-hierarchy",
        "title": f"Phase {phase_id}",
        "deliveryStatus": status,
        "dependsOn": depends_on or [],
    }


def _task_record(
    task_ref: str,
    phase_id: str,
    *,
    status: str = "backlog",
    r_ids: list[str] | None = None,
    parent_task_unit: str | None = None,
) -> dict[str, Any]:
    return {
        "unitId": f"339-task-{task_ref.replace('.', '-')}",
        "artifactType": "task",
        "taskRef": task_ref,
        "phaseUnitId": f"339-phase-{phase_id}",
        "prdUnitId": "339-prd-hierarchy",
        "title": f"Task {task_ref}",
        "completionStatus": status,
        "rIds": r_ids or [f"R{task_ref.replace('.', '')}"],
        "scenarios": [f"scenario-{task_ref}"],
        "parentTaskUnitId": parent_task_unit,
    }


def _many_phase_records(count: int = 12) -> list[dict[str, Any]]:
    records = [_prd_record()]
    for idx in range(1, count + 1):
        depends = [str(idx - 1)] if idx > 1 else []
        records.append(_phase_record(str(idx), depends_on=depends))
        records.append(_task_record(f"{idx}.1", str(idx), status="done" if idx < 3 else "backlog"))
    return records


def test_phase_milestone_spec_has_dependency_and_delivery_status() -> None:
    record = _phase_record("5", depends_on=["4"], status="in_flight")
    spec = plp.build_phase_milestone_spec(record, project_key="demo", prd_project_entity_id="proj-1")
    assert spec["verdict"] == "pass"
    assert spec["linearEntity"] == "Milestone"
    assert spec["projectId"] == "proj-1"
    owned = spec["ownedFields"]
    assert owned["phaseId"] == "5"
    assert owned["dependsOn"] == ["4"]
    assert owned["deliveryStatus"] == "in_flight"
    assert spec["marker"] == "sw:unit:339-phase-5"


def test_task_issue_spec_has_parentage_refs_and_traceability() -> None:
    record = _task_record("5.2", "5", status="done", r_ids=["R5", "R12"])
    spec = plp.build_task_issue_spec(
        record,
        project_key="demo",
        prd_project_entity_id="proj-1",
        phase_milestone_entity_id="ms-5",
        parent_issue_entity_id="iss-5-1",
    )
    assert spec["verdict"] == "pass"
    assert spec["linearEntity"] == "Issue"
    assert spec["milestoneId"] == "ms-5"
    assert spec["parentIssueId"] == "iss-5-1"
    assert spec["subIssue"] is True
    owned = spec["ownedFields"]
    assert owned["taskRef"] == "5.2"
    assert owned["phaseUnitId"] == "339-phase-5"
    assert owned["rIds"] == ["R5", "R12"]
    assert owned["scenarios"] == ["scenario-5.2"]
    assert owned["completionStatus"] == "done"


def test_many_phase_hierarchy_rebuild_preserves_dependency_order(tmp_path: Path) -> None:
    store = plp.LinearProjectionRebuildStore()
    records = _many_phase_records(12)
    first = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        records,
        project_key="demo",
        store=store,
    )
    assert first["verdict"] == "pass", first
    assert first["counts"]["Milestone"] == 12
    assert first["counts"]["Issue"] == 12

    milestones = sorted(
        store.milestones.values(),
        key=lambda row: int(str((row.get("ownedFields") or {}).get("phaseId") or "0")),
    )
    assert len(milestones) == 12
    assert milestones[0]["ownedFields"]["dependsOn"] == []
    assert milestones[5]["ownedFields"]["dependsOn"] == ["5"]

    tasks = list(store.issues.values())
    assert all(task.get("milestoneId") for task in tasks)
    assert all(task.get("subIssue") for task in tasks)

    second = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        records,
        project_key="demo",
        store=store,
    )
    assert second["verdict"] == "pass"
    assert second["created"] == 0
    assert second["counts"]["Milestone"] == 12


def test_resumable_reconcile_survives_interrupt_and_repeat(tmp_path: Path) -> None:
    records = _many_phase_records(8)
    store = plp.LinearProjectionRebuildStore()

    first = facade.reconcile_linear_operator_projection_from_semantic_store(
        tmp_path,
        records,
        project_key="demo",
        store=store,
        resume=False,
    )
    assert first["verdict"] == "pass", first
    assert first["completedSteps"] == list(plp.LINEAR_HIERARCHY_REBUILD_STEPS)

    interrupted = facade.reconcile_linear_operator_projection_from_semantic_store(
        tmp_path,
        records[:3],
        project_key="demo",
        store=store,
        resume=False,
    )
    assert interrupted["verdict"] == "pass"

    resumed = facade.reconcile_linear_operator_projection_from_semantic_store(
        tmp_path,
        records,
        project_key="demo",
        store=store,
        resume=True,
    )
    assert resumed["verdict"] == "pass", resumed
    assert resumed["counts"]["Milestone"] == 8

    repeat = facade.reconcile_linear_operator_projection_from_semantic_store(
        tmp_path,
        records,
        project_key="demo",
        store=store,
        resume=False,
    )
    assert repeat["verdict"] == "pass"
    assert repeat["created"] == 0


def test_tombstone_stale_entities_after_semantic_shrink(tmp_path: Path) -> None:
    store = plp.LinearProjectionRebuildStore()
    full = _many_phase_records(6)
    built = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        full,
        project_key="demo",
        store=store,
    )
    assert built["verdict"] == "pass"
    assert built["counts"]["Milestone"] == 6

    shrunk = [record for record in full if record.get("artifactType") != "phase" or record.get("phaseId") in {"1", "2"}]
    pruned = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        shrunk,
        project_key="demo",
        store=store,
        tombstone_stale=True,
    )
    assert pruned["verdict"] == "pass"
    assert pruned["tombstone"]["tombstoneCount"] >= 4
    active = [row for row in store.milestones.values() if not row.get("tombstoned")]
    assert len(active) == 2


def test_semantic_authority_blocks_operator_drift_without_overwrite(tmp_path: Path) -> None:
    records = [_prd_record(), _phase_record("1"), _task_record("1.1", "1")]
    store = plp.LinearProjectionRebuildStore()
    first = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        records,
        project_key="demo",
        store=store,
    )
    assert first["verdict"] == "pass"
    phase = store.find_by_marker("sw:unit:339-phase-1", "Milestone")
    assert phase is not None
    ps.projection_ledger_upsert(
        tmp_path,
        unit_id="339-phase-1",
        artifact_type="phase",
        provider="linear",
        entity_id=phase["entityId"],
        owned_fields={"title": "Operator edited", "status": "backlog", "marker": "sw:unit:339-phase-1"},
        marker="sw:unit:339-phase-1",
    )
    drifted = list(records)
    drifted[1] = {**drifted[1], "deliveryStatus": "done"}
    blocked = plp.rebuild_linear_projection_from_semantic_store(
        tmp_path,
        drifted,
        project_key="demo",
        store=store,
        overwrite_drift=False,
    )
    assert blocked["verdict"] == "fail"
    assert blocked["error"] == "projection_drift"
