"""PRD 339 R33/R34 — Linear operator browse documentation and gap-079 UI answerability."""

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
from planning_linear_client import operator_browse_checklist_gate


def _semantic_records() -> list[dict[str, Any]]:
    return [
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


def _r1_evidence_from_projection_specs() -> dict[str, Any]:
    records = _semantic_records()
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


def test_operator_browse_doc_markers_present(repo_root: Path) -> None:
    """R33 — linear.md documents adapter contract and browse checklist."""
    gate = operator_browse_checklist_gate(repo_root)
    assert gate.get("verdict") == "ok", gate
    assert gate.get("checklist", {}).get("bodyOpenIsFailure") is True


def test_linear_operator_browse_mapped_views_cover_prd_gap_task() -> None:
    """R33 — mapped views exist for PRD, Gap, and Task browse questions."""
    payload = facade.linear_operator_browse_mapped_views()
    views = payload["views"]
    assert set(views) >= {"prd", "gap", "task"}
    assert views["prd"]["linearSurface"] == "Project"
    assert views["gap"]["linearSurface"] == "Issue"
    assert "sub-issue" in views["task"]["linearSurface"]
    assert 1 in views["gap"]["browseQuestions"]
    assert 3 in views["task"]["browseQuestions"]


def test_assert_linear_not_lcd_labels_only_rejects_issue_labels_surface() -> None:
    """R33 — LCD issue+labels-only surfaces are rejected."""
    out = facade.assert_linear_not_lcd_labels_only(["issue", "issue+labels"])
    assert out["verdict"] == "fail"
    assert out["error"] == "linear-lcd-labels-only-rejected"


def test_assert_linear_not_lcd_labels_only_accepts_full_projection() -> None:
    """R33 — Project/Document/Milestone hierarchy passes LCD-only guard."""
    out = facade.assert_linear_not_lcd_labels_only()
    assert out["verdict"] == "pass"


def test_gap079_linear_ui_answerability_blocked_without_prd061(tmp_path: Path) -> None:
    """R34 — prerequisite readiness is required before browse answerability passes."""
    out = facade.gap079_linear_ui_answerability(tmp_path, evidence=_r1_evidence_from_projection_specs())
    assert out["verdict"] == "fail"
    assert out["error"] == "prd061-prerequisite-blocked"
    assert out["prd061Gate"]["verdict"] == "blocked"


def test_gap079_linear_ui_answerability(repo_root: Path) -> None:
    """R33/R34 — gap-079 browse questions answerable from mapped views after PRD 061 green."""
    out = facade.gap079_linear_ui_answerability(
        repo_root,
        evidence=_r1_evidence_from_projection_specs(),
    )
    assert out["verdict"] == "pass", out
    assert out["semanticAuthority"] == "portable-graph"
    assert out["bodyOpenIsFailure"] is True
    assert out["metadataCheck"]["verdict"] == "pass"
    questions = out["questions"]
    assert all(row["answerable"] for row in questions.values())
    assert set((out["mappedViews"]["views"]).keys()) >= {"prd", "gap", "task"}


def test_gap079_linear_ui_answerability_rejects_body_open_metadata(repo_root: Path) -> None:
    """R33 — opening markdown bodies during browse fails the harness."""
    evidence = _r1_evidence_from_projection_specs()
    evidence["1"]["bodyOpened"] = True
    out = facade.gap079_linear_ui_answerability(repo_root, evidence=evidence)
    assert out["verdict"] == "fail"
    assert out["error"] == "r1-body-open"


def test_gap079_linear_ui_answerability_cli_after_prerequisite(repo_root: Path) -> None:
    """R34 — operator browse checklist gate is wired on the linear client CLI."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root / "scripts")
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/planning_linear_client.py"),
            str(repo_root),
            "operator-browse-checklist-gate",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, (proc.stdout or "") + (proc.stderr or "")
    payload = json.loads(proc.stdout)
    assert payload.get("verdict") == "ok"
    assert payload.get("gate") == "operator-browse-checklist-gate"
