"""PRD 339 R32/R33 — bundle closeout for visibility nomenclature and Linear browse."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_linear_projection as plp
import planning_store_facade as facade
from prd339_bundle_closeout import (
    GAP_001_ABSORB_UNIT_ID,
    GAP_079_ABSORB_UNIT_ID,
    prd339_bundle_closeout_milestone,
)
from prd339_visibility_nomenclature import check_visibility_nomenclature


def _r1_evidence_from_projection_specs() -> dict[str, Any]:
    records = [
        {
            "unitId": "339-prd-browse",
            "artifactType": "prd",
            "title": "Operator browse",
            "status": "in_flight",
            "content": "# Operator browse\n",
            "links": ["https://linear.app/example/project/browse"],
        },
        {
            "unitId": "339-bs-browse",
            "artifactType": "brainstorm",
            "prdUnitId": "339-prd-browse",
            "title": "Browse brainstorm",
            "content": "# Browse brainstorm\n",
        },
        {
            "unitId": "gap-079-browse",
            "artifactType": "gap",
            "prdUnitId": "339-prd-browse",
            "title": "Linear operator browse gap",
            "lifecycle": "open",
            "prerequisites": ["gap-078-prerequisite"],
            "absorbs": ["339-prd-browse"],
            "content": "# Gap 079 browse\n",
        },
        {
            "unitId": "339-phase-browse",
            "artifactType": "phase",
            "phaseId": "12",
            "prdUnitId": "339-prd-browse",
            "title": "Document browse",
            "deliveryStatus": "in_flight",
            "dependsOn": [],
        },
        {
            "unitId": "339-task-browse",
            "artifactType": "task",
            "taskRef": "12.3",
            "phaseUnitId": "339-phase-browse",
            "prdUnitId": "339-prd-browse",
            "title": "Validate browse answerability",
            "completionStatus": "backlog",
            "rIds": ["R33", "R34"],
            "scenarios": ["gap079_linear_ui_answerability"],
        },
    ]
    prd = records[0]
    brainstorm = records[1]
    gap = records[2]
    phase = records[3]
    task = records[4]
    prd_spec = plp.build_prd_project_spec(prd, project_key="demo")
    brainstorm_spec = plp.build_brainstorm_document_spec(
        brainstorm,
        project_key="demo",
        prd_project_entity_id="proj-browse",
    )
    gap_spec = plp.build_gap_issue_spec(
        gap,
        project_key="demo",
        prd_project_entity_id="proj-browse",
    )
    phase_spec = plp.build_phase_milestone_spec(
        phase,
        project_key="demo",
        prd_project_entity_id="proj-browse",
    )
    task_spec = plp.build_task_issue_spec(
        task,
        project_key="demo",
        prd_project_entity_id="proj-browse",
        phase_milestone_entity_id="ms-browse",
    )
    assert all(spec["verdict"] == "pass" for spec in (prd_spec, brainstorm_spec, gap_spec, phase_spec, task_spec))
    return {
        "1": {
            "fields": ["projectMembership", "gapLabelOrField", "gapIssueIdentity"],
            "bodyOpened": False,
            "gapProjectMembership": gap_spec.get("projectMembership"),
        },
        "2": {
            "fields": [
                "documentAttachmentOrMembership",
                "brainstormIdentity",
                "prdProjectLink",
            ],
            "bodyOpened": False,
            "documentAttachment": brainstorm_spec.get("attachedToProject"),
        },
        "3": {
            "fields": [
                "issueSemanticStatus",
                "milestonePhaseMembership",
                "milestoneProgress",
            ],
            "bodyOpened": False,
            "milestoneId": task_spec.get("milestoneId"),
            "phaseDeliveryStatus": phase_spec["ownedFields"].get("deliveryStatus"),
        },
        "4": {
            "fields": [
                "initiativeOrProgramDiscriminator",
                "programSemanticStatus",
                "substituteViewsOrFilters",
            ],
            "bodyOpened": False,
            "substituteViews": facade.r1_4_substitute_views().get("requiredViews"),
        },
    }


def test_visibility_tier_vs_storage_placement(repo_root: Path) -> None:
    """R32 — gap-001 nomenclature is reconciled across configuration surfaces."""
    result = check_visibility_nomenclature(repo_root)
    assert result["scenario"] == "visibility_tier_vs_storage_placement"
    assert result["verdict"] == "pass", result
    assert GAP_001_ABSORB_UNIT_ID.startswith("gap-001-")


def test_gap079_linear_ui_answerability(repo_root: Path) -> None:
    """R33/R34 — gap-079 browse questions pass without markdown bodies."""
    out = facade.gap079_linear_ui_answerability(
        repo_root,
        evidence=_r1_evidence_from_projection_specs(),
    )
    assert out["verdict"] == "pass", out
    assert out["bodyOpenIsFailure"] is True
    assert out["gapUnitId"] == GAP_079_ABSORB_UNIT_ID
    questions = out["questions"]
    assert all(row["answerable"] for row in questions.values())


def test_gap079_linear_ui_answerability_rejects_body_open(repo_root: Path) -> None:
    """R33 — opening markdown bodies during browse fails the harness."""
    evidence = _r1_evidence_from_projection_specs()
    evidence["1"]["bodyOpened"] = True
    out = facade.gap079_linear_ui_answerability(repo_root, evidence=evidence)
    assert out["verdict"] == "fail"
    assert out["error"] == "r1-body-open"


def test_bundle_closeout_gate_ready_on_repo(repo_root: Path) -> None:
    """R32/R33 — bundle closeout milestone is green on merged phase work."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "scripts")
    proc = subprocess.run(
        [sys.executable, str(repo_root / "scripts/prd339_bundle_closeout.py"), str(repo_root)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    out = json.loads(proc.stdout)
    assert out.get("verdict") == "ready", out
    assert out.get("requirements") == ["R32", "R33"]
