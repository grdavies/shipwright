"""PRD 066 phase 9 — GitHub Projects R18 parity + R19 body-store retention."""
from __future__ import annotations

import sys
from pathlib import Path

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_github_projects_v2 as gp
import planning_store as ps


def _base_cfg(**github_projects_extra: object) -> dict:
    section = {
        "enabled": True,
        "ownerLogin": "acme",
        "projectNumber": 1,
        "fieldMap": {
            "status": "Status",
            "artifactType": "Artifact",
            "unitId": "Unit",
            "absorbs": "Absorbs",
            "brainstormFeed": "Brainstorms",
            "phaseProgress": "Phases",
        },
        "budget": {"maxCalls": 5},
    }
    section.update(github_projects_extra)
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "planning",
                "storeLocation": {"mode": "separate-project", "owner": "acme", "repo": "planning"},
                "operatorProjection": {"githubProjects": section},
            }
        },
        "host": {"provider": "github"},
    }


def _r1_evidence(*, include_program: bool) -> dict:
    browse = ps.operator_projection_contract()["r1BrowseContract"]
    evidence = {
        "1": {"fields": browse["questions"]["1"]["cardVisibleFields"], "bodyOpened": False},
        "2": {"fields": browse["questions"]["2"]["cardVisibleFields"], "bodyOpened": False},
        "3": {"fields": browse["questions"]["3"]["cardVisibleFields"], "bodyOpened": False},
        "4": {
            "fields": list(browse["questions"]["4"]["cardVisibleFields"]),
            "bodyOpened": False,
        },
    }
    if not include_program:
        evidence["4"]["fields"] = [
            f for f in evidence["4"]["fields"] if f != "initiativeOrProgramDiscriminator"
        ]
    return evidence


def test_r18_status_only_is_not_r1_4_complete() -> None:
    """R18 — Status (+ views) alone is not R1(4)-complete."""
    cfg = _base_cfg()  # fieldMap has Status but no program/initiative
    disc = gp.resolve_program_discriminator(cfg)
    assert disc["present"] is False
    assert disc["mode"] == "none"
    assert disc["r14Supported"] is False
    assert disc["statusOnlyComplete"] is False

    harness = gp.projects_r1_harness(cfg, evidence=_r1_evidence(include_program=False))
    assert harness["verdict"] == "fail"
    assert harness["error"] == "r1-4-program-discriminator-missing"
    assert harness["questions"].get("1", {}).get("answerable") is True
    assert harness["questions"].get("4", {}).get("answerable") is False


def test_r18_program_field_discriminator_makes_r1_green() -> None:
    """R18 — required program/initiative fieldMap key satisfies R1(4)."""
    cfg = _base_cfg(
        fieldMap={
            "status": "Status",
            "absorbs": "Absorbs",
            "brainstormFeed": "Brainstorms",
            "phaseProgress": "Phases",
            "program": "Program",
        }
    )
    disc = gp.resolve_program_discriminator(cfg)
    assert disc["present"] is True
    assert disc["mode"] == "field"
    assert disc["semanticKey"] == "program"
    assert disc["r14Supported"] is True

    harness = gp.projects_r1_harness(cfg, evidence=_r1_evidence(include_program=True))
    assert harness["verdict"] == "pass"
    assert all(row["answerable"] for row in harness["questions"].values())
    assert harness["statusOnlyComplete"] is False


def test_r18_project_per_program_discriminator() -> None:
    """R18 — project-per-program mode is a valid discriminator without program field."""
    cfg = _base_cfg(programMode="project-per-program")
    disc = gp.resolve_program_discriminator(cfg)
    assert disc["present"] is True
    assert disc["mode"] == "project-per-program"
    assert disc["r14Supported"] is True

    harness = gp.projects_r1_harness(cfg, evidence=_r1_evidence(include_program=True))
    assert harness["verdict"] == "pass"


def test_r18_initiative_cycle_degradations_documented() -> None:
    """R18 — Initiative/Cycle analogues appear as explicit degradations (not silent)."""
    table = gp.projects_degradation_table()
    assert table["verdict"] == "ok"
    by_concept = {row["concept"]: row for row in table["rows"]}
    initiative = by_concept["initiative"]
    assert initiative["nativeSupported"] is False
    assert initiative["degradationClass"] == "degraded-required-discriminator"
    assert "program" in initiative["analogue"].lower() or "discriminator" in initiative["analogue"].lower()

    cycle = by_concept["cycle"]
    assert cycle["nativeSupported"] is False
    assert cycle["degradationClass"] == "degraded-optional"
    assert cycle["requiredForR1"] is False

    notices = gp.projects_degradation_notices(cfg=_base_cfg())
    assert any(n.get("concept") == "initiative" for n in notices["notices"])
    assert any(n.get("concept") == "cycle" for n in notices["notices"])
    for notice in notices["notices"]:
        assert notice.get("missingNative")
        assert notice.get("fallbackBrowsePath")
        assert "optionalFieldsImprove" in notice


def test_r19_issues_remain_body_store() -> None:
    """R19 — github-issues backends keep Issues as the unit body store under Projects projection."""
    contract = gp.projects_body_store_contract()
    assert contract["verdict"] == "ok"
    assert contract["bodyStore"] == "github-issues"
    assert contract["projectionSurface"] == "github-projects"
    assert contract["abandonIssueBodies"] is False
    assert contract["freezeAuthority"] == "lcd-issue-body"


def test_r18_assert_helper_fails_without_discriminator() -> None:
    """R18 harness helper — R1(4) fails closed when discriminator absent."""
    cfg = _base_cfg()
    result = gp.assert_projects_r1_answerability(cfg, _r1_evidence(include_program=True))
    assert result["verdict"] == "fail"
    assert result["error"] == "r1-4-program-discriminator-missing"
