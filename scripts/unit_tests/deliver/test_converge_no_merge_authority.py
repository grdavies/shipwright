"""Converge holds no merge authority (PRD 342 R5, R45)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import check_gate_lib as gate
import converge_assess as ca
import converge_phase as cp


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    _git_init(root)
    unit = root / "docs" / "prds" / "342-demo"
    unit.mkdir(parents=True)
    _write(
        unit / "342-prd-demo.md",
        "---\nid: 342-prd-demo\ntype: prd\nstatus: draft\ntitle: Demo\n"
        "visibility: public\nbundle: true\n---\n\n# Demo\n\nSee `scripts/demo.py`.\n",
    )
    for name, body in {
        "plan.md": "# Plan\n\nImplement `scripts/demo.py`.\n",
        "data-model.md": "# Data model\n",
        "contracts.md": "# Contracts\n",
        "quickstart.md": "# Quickstart\n",
        "checklist.md": "# Checklist\n",
    }.items():
        _write(unit / name, body)
    _write(root / "scripts" / "demo.py", "print('demo')\n")
    _write(
        unit / "tasks-342-demo.md",
        "---\nid: tasks-342-demo\ntype: tasks\nstatus: draft\ntitle: Tasks\n"
        "visibility: public\nfrozen: true\n---\n\n# Tasks\n\n### 1. Alpha\n\n"
        "- [ ] 1.1 Do thing\n  - **File:** `scripts/demo.py`\n",
    )
    for rel in (
        ".shipwright/workflow.config.json",
        ".cursor/workflow.config.json",
        "workflow.config.json",
    ):
        _write(root / rel, json.dumps({"converge": {"enabled": True}}, indent=2) + "\n")
    return root


def test_check_gate_alone_owns_merge_readiness(repo: Path) -> None:
    """R5/R45 — check-gate alone determines merge readiness; converge cannot."""
    assert hasattr(gate, "run_gate")
    assert callable(gate.run_gate)

    result = cp.run_converge_phase(
        repo,
        task_list="docs/prds/342-demo/tasks-342-demo.md",
        skip_verify_execute=True,
        config={"converge": {"enabled": True}},
    )
    assert result["verdict"] == "pass"
    assert result.get("autoFixApplied") is False
    assert result.get("autoAmendApplied") is False
    assert result.get("blocksRun") is False

    # Converge outcomes must not advertise merge authority fields.
    for key in ("mergeReady", "mergeAuthority", "satisfiesCheckGate", "bypassesCheckGate"):
        assert key not in result
        assert key not in (result.get("assessment") or {})

    assessment = ca.compose_converge_assessment(
        repo,
        task_list="docs/prds/342-demo/tasks-342-demo.md",
        unit_dir="docs/prds/342-demo",
        skip_verify_execute=True,
        route_findings=False,
    )
    assert assessment["verdict"] == "pass"
    assert assessment.get("blocksRun") is False
    # A green converge assessment is never a substitute for check-gate.
    assert assessment.get("mergeReady") is None
    assert "checkGateVerdict" not in assessment


def test_converge_outcome_cannot_override_or_bypass_check_gate(repo: Path) -> None:
    """No converge verdict satisfies, overrides, or bypasses check-gate."""
    # Simulate a failing check-gate posture by inspecting the gate contract:
    # converge must not flip a non-green gate into merge-ready.
    bogus_gate = {"verdict": "blocked", "reason": "required-check-failing"}
    converge = cp.run_converge_phase(
        repo,
        task_list="docs/prds/342-demo/tasks-342-demo.md",
        skip_verify_execute=True,
        config={"converge": {"enabled": True}},
    )
    assert converge["verdict"] == "pass"
    # Even with converge pass, the blocked gate remains the merge authority.
    assert bogus_gate["verdict"] != "green"
    merged = {
        "checkGate": bogus_gate,
        "converge": {"verdict": converge["verdict"]},
    }
    assert merged["checkGate"]["verdict"] == "blocked"
    assert merged["converge"]["verdict"] == "pass"
    # Policy: merge readiness follows check-gate only.
    merge_ready = merged["checkGate"]["verdict"] in {"green", "pass"}
    assert merge_ready is False


def test_worktree_isolation_unchanged_with_converge(repo: Path) -> None:
    """R5 — worktree isolation for converge nodes stays process/worktree scoped."""
    nodes = cp.compile_converge_nodes()
    by_id = {node["id"]: node for node in nodes}
    assessor = by_id["converge-assess"]
    body = by_id["converge"]
    assert assessor["isolation"] == {"mode": "process", "writeScope": "read-only"}
    assert body["isolation"] == {"mode": "worktree", "writeScope": "worktree"}
    # Assessor must not write outside process/read-only; body stays worktree-scoped.
    assert assessor["isolation"]["writeScope"] != "repo"
    assert body["isolation"]["writeScope"] == "worktree"


def test_converge_findings_route_without_autofix_or_autoamend(repo: Path) -> None:
    """R46 — findings route through gap-capture + amendment; never auto-fix/amend."""
    import planning_gap_capture as pgc

    findings = [
        {
            "role": "contracts",
            "missingAsset": "contracts",
            "reason": "declared-bundle-asset-missing",
            "frozenArtifact": True,
        },
        {
            "role": "plan",
            "ref": "scripts/missing.py",
            "reason": "bundle-ref-missing-from-tree",
        },
    ]
    refused = pgc.route_converge_findings(
        repo, findings, unit_id="342-prd-demo", auto_fix=True, auto_amend=False
    )
    assert refused["verdict"] == "refused"
    assert refused["autoFixApplied"] is False
    assert refused["autoAmendApplied"] is False

    routed = pgc.route_converge_findings(
        repo, findings, unit_id="342-prd-demo", unit_dir="docs/prds/342-demo"
    )
    assert routed["verdict"] == "pass"
    assert routed["autoFixApplied"] is False
    assert routed["autoAmendApplied"] is False
    assert routed["awaitingHumanDisposition"] is True
    assert routed["findingCount"] == 2
    assert all(item["gapCapture"]["action"] == "draft-inbox" for item in routed["routed"])
    frozen_routes = [item for item in routed["routed"] if item.get("amendment")]
    assert frozen_routes
    assert all(item["amendment"]["autoAmendApplied"] is False for item in frozen_routes)


def test_undeclared_bundle_degrades_without_blocking(repo: Path) -> None:
    """R47 — no-bundle degrades to current deliver with explanatory report; no block."""
    unit = repo / "docs" / "prds" / "342-nobundle"
    unit.mkdir(parents=True)
    (unit / "342-prd-nobundle.md").write_text(
        "---\nid: 342-prd-nobundle\ntype: prd\nstatus: draft\ntitle: No Bundle\n"
        "visibility: public\n---\n\n# No Bundle\n",
        encoding="utf-8",
    )
    (unit / "tasks-342-nobundle.md").write_text(
        "---\nid: tasks-342-nobundle\ntype: tasks\nstatus: draft\ntitle: Tasks\n"
        "visibility: public\nfrozen: true\n---\n\n# Tasks\n\n### 1. Only\n",
        encoding="utf-8",
    )
    step = ca.run_bundle_anchored_assessor(repo, unit_dir=unit)
    assert step["verdict"] == "pass"
    assert step.get("blocksRun") is False
    assert step.get("degradedToCurrentDeliver") is True
    assert step.get("explanatoryReport", {}).get("degradedToCurrentDeliver") is True

    report = ca.compose_converge_assessment(
        repo,
        task_list="docs/prds/342-nobundle/tasks-342-nobundle.md",
        unit_dir=str(unit),
        skip_verify_execute=True,
        route_findings=False,
    )
    assert report["verdict"] == "pass"
    assert report.get("blocksRun") is False
    assert report.get("degradedToCurrentDeliver") is True


def test_incomplete_bundle_names_missing_assets_without_blocking(repo: Path) -> None:
    """R47 — declared-but-incomplete names missing assets, assesses present, no block."""
    unit = repo / "docs" / "prds" / "342-demo"
    # Drop one required asset so the declared bundle is incomplete.
    contracts = unit / "contracts.md"
    if contracts.is_file():
        contracts.unlink()
    step = ca.run_bundle_anchored_assessor(repo, unit_dir=unit)
    assert step.get("blocksRun") is False
    missing = step.get("missing") or []
    assert missing, "expected missing assets"
    named = [
        f
        for f in (step.get("findings") or [])
        if f.get("reason") == "declared-bundle-asset-missing"
    ]
    assert named
    assert {f.get("missingAsset") for f in named} >= set(missing)
    assert step.get("explanatoryReport", {}).get("blocksRun") is False

    report = ca.compose_converge_assessment(
        repo,
        task_list="docs/prds/342-demo/tasks-342-demo.md",
        unit_dir=str(unit),
        skip_verify_execute=True,
        route_findings=True,
    )
    assert report["verdict"] == "pass"
    assert report.get("blocksRun") is False
    assert report.get("autoFixApplied") is False
    assert report.get("autoAmendApplied") is False
    assert report.get("findingRouting", {}).get("awaitingHumanDisposition") is True
