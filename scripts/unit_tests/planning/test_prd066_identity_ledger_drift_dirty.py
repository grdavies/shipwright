"""PRD 066 phase 2 — identity ledger, typed drift, dirty resume (R2, R5, R27, R28)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_store as ps


@pytest.fixture()
def ledger_root(tmp_path: Path) -> Path:
    return tmp_path


def _browse_evidence() -> dict:
    contract = ps.operator_projection_contract()
    browse = contract["r1BrowseContract"]
    return {
        "1": {"fields": browse["questions"]["1"]["cardVisibleFields"], "bodyOpened": False},
        "2": {"fields": browse["questions"]["2"]["cardVisibleFields"], "bodyOpened": False},
        "3": {"fields": browse["questions"]["3"]["cardVisibleFields"], "bodyOpened": False},
        "4": {"fields": browse["questions"]["4"]["cardVisibleFields"], "bodyOpened": False},
    }


def test_r2_portable_graph_remains_sot_on_rebuild(ledger_root: Path) -> None:
    """R2 — fixture rebuild does not promote Linear entities to freeze authority."""
    graph = {
        "freezeAuthority": "portable-graph",
        "units": [
            {
                "unitId": "066-prd",
                "artifactType": "prd",
                "entityId": "lin-proj-1",
                "ownedFields": {"title": "PRD 066", "status": "in_flight"},
                "marker": "sw:unit:066-prd",
            }
        ],
    }
    authority = ps.assert_portable_graph_authority(
        graph, projection={"freezeAuthority": "derived", "isSourceOfTruth": False}
    )
    assert authority["verdict"] == "pass"
    assert authority["projectionRebuildable"] is True

    bad = ps.assert_portable_graph_authority(
        graph, projection={"freezeAuthority": "linear", "isSourceOfTruth": True}
    )
    assert bad["verdict"] == "fail"
    assert bad["error"] in {"projection-claimed-freeze-authority", "projection-claimed-sot"}

    rebuilt = ps.rebuild_projection_from_graph(ledger_root, graph, provider="linear")
    assert rebuilt["verdict"] == "pass"
    assert rebuilt["freezeAuthority"] == "portable-graph"
    # Idempotent second rebuild
    again = ps.rebuild_projection_from_graph(ledger_root, graph, provider="linear")
    assert again["verdict"] == "pass"
    lookup = ps.projection_ledger_lookup(
        ledger_root, unit_id="066-prd", artifact_type="prd", provider="linear"
    )
    assert lookup["verdict"] == "pass"
    assert lookup["entry"]["entityId"] == "lin-proj-1"


def test_r5_identity_ledger_upsert_marker_and_duplicates(ledger_root: Path) -> None:
    """R5 — upsert keys, marker fallback, duplicate reconciliation."""
    up = ps.projection_ledger_upsert(
        ledger_root,
        unit_id="066-prd",
        artifact_type="prd",
        provider="linear",
        entity_id="proj-1",
        owned_fields={"title": "PRD 066"},
        marker="sw:unit:066-prd",
    )
    assert up["verdict"] == "pass"
    found = ps.projection_ledger_discover_by_marker(
        ledger_root, provider="linear", marker="sw:unit:066-prd"
    )
    assert found["verdict"] == "pass"
    assert found["entry"]["entityId"] == "proj-1"

    ok = ps.projection_ledger_reconcile_duplicates(
        ledger_root,
        unit_id="066-prd",
        artifact_type="prd",
        provider="linear",
        candidate_entity_ids=["proj-1", "proj-dup"],
    )
    assert ok["verdict"] == "pass"
    assert ok["winner"] == "proj-1"
    assert ok["collapsed"] is True

    fail = ps.projection_ledger_reconcile_duplicates(
        ledger_root,
        unit_id="missing",
        artifact_type="prd",
        provider="linear",
        candidate_entity_ids=["a", "b"],
    )
    assert fail["verdict"] == "fail"
    assert fail["error"] == "ledger-duplicate-entities"

    # Projects provider also supported
    projects = ps.projection_ledger_upsert(
        ledger_root,
        unit_id="066-prd",
        artifact_type="prd",
        provider="github-projects",
        entity_id="pv-1",
        owned_fields={"title": "PRD 066"},
        marker="sw:unit:066-prd",
    )
    assert projects["verdict"] == "pass"


def test_r27_typed_drift_halts_unless_overwrite_audited(ledger_root: Path) -> None:
    """R27 — drifted owned fields halt; overwrite flag audits; default never clobbers."""
    ps.projection_ledger_upsert(
        ledger_root,
        unit_id="066-task",
        artifact_type="task",
        provider="linear",
        entity_id="iss-1",
        owned_fields={"title": "Task A", "status": "backlog"},
    )
    halted = ps.check_projection_drift(
        ledger_root,
        unit_id="066-task",
        artifact_type="task",
        provider="linear",
        provider_owned_fields={"title": "Human edited", "status": "backlog"},
        overwrite_drift=False,
    )
    assert halted["verdict"] == "fail"
    assert halted["error"] == "projection_drift"

    overwritten = ps.check_projection_drift(
        ledger_root,
        unit_id="066-task",
        artifact_type="task",
        provider="linear",
        provider_owned_fields={"title": "Human edited", "status": "backlog"},
        overwrite_drift=True,
        audit_actor="tester",
    )
    assert overwritten["verdict"] == "pass"
    assert overwritten["overwritten"] is True
    assert overwritten["audit"]["actor"] == "tester"
    ledger = ps.load_projection_ledger(ledger_root)
    assert ledger["audit"], "overwrite must leave audit trail"


def test_r28_dirty_blocks_r1_and_resume_clears(ledger_root: Path) -> None:
    """R28 — budget halt → dirty; R1 fails while dirty; resume completes without duplicates."""
    ps.projection_ledger_upsert(
        ledger_root,
        unit_id="066-prd",
        artifact_type="prd",
        provider="linear",
        entity_id="proj-1",
        owned_fields={"title": "PRD 066"},
    )
    dirty = ps.set_projection_dirty(ledger_root, reason="budget-exhaustion")
    assert dirty["verdict"] == "pass"
    assert dirty["dirty"] is True
    assert ps.projection_is_dirty(ledger_root) is True

    blocked = ps.assert_r1_answerability_while_clean(ledger_root, _browse_evidence())
    assert blocked["verdict"] == "fail"
    assert blocked["error"] == "projection-dirty"

    rebuild_blocked = ps.rebuild_projection_from_graph(
        ledger_root,
        {"freezeAuthority": "portable-graph", "units": []},
        provider="linear",
    )
    assert rebuild_blocked["verdict"] == "fail"
    assert rebuild_blocked["error"] == "projection-dirty"

    resumed = ps.resume_projection_from_checkpoint(ledger_root)
    assert resumed["verdict"] == "pass"
    assert resumed["dirty"] is False
    assert ps.projection_is_dirty(ledger_root) is False
    ok = ps.assert_r1_answerability_while_clean(ledger_root, _browse_evidence())
    assert ok["verdict"] == "pass"
