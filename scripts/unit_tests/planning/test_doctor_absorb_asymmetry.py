"""PRD 094 R18 — doctor reports gap absorbed-by without matching PRD absorbs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body
from planning_store import IssueStoreBackend, doctor, doctor_absorb_asymmetry


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "absorb-asymmetry-094") -> dict[str, Any]:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "host": {"provider": "github"},
    }


def _seed_prd_gap_pair(
    root: Path,
    cfg: dict[str, Any],
    *,
    prd_unit: str,
    gap_unit: str,
    prd_absorbs: list[str] | None,
    gap_absorbed_by: str | None,
) -> IssueStoreBackend:
    project_key = cfg["planning"]["store"]["projectKey"]
    absorbs_line = ""
    if prd_absorbs is not None:
        absorbs_line = f"absorbs: [{', '.join(prd_absorbs)}]\n"
    prd_content = (
        f"---\n"
        f"id: {prd_unit}\n"
        f"type: prd\n"
        f"status: open\n"
        f"visibility: public\n"
        f"{absorbs_line}"
        f"---\n"
        f"# PRD 094 asymmetry fixture\n"
    )
    absorbed_line = ""
    if gap_absorbed_by:
        absorbed_line = f"absorbed-by: {gap_absorbed_by}\n"
    gap_content = (
        f"---\n"
        f"id: {gap_unit}\n"
        f"type: gap\n"
        f"status: open\n"
        f"visibility: public\n"
        f"{absorbed_line}"
        f"---\n"
        f"# Gap asymmetry fixture\n"
    )
    backend = IssueStoreBackend(root, cfg)
    prd_path = f"docs/prds/094-asymmetry/{prd_unit}.md"
    gap_path = f"docs/planning/gap/{gap_unit}/{gap_unit}.md"
    assert backend.put(prd_unit, prd_path, prd_content).verdict == "ok"
    assert backend.put(gap_unit, gap_path, gap_content).verdict == "ok"
    idx_path = root / ".cursor/hooks/state/issue-store-unit-index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    for unit_id, body_path in ((prd_unit, prd_path), (gap_unit, gap_path)):
        issue_id = index["units"][f"{project_key}:{unit_id}"]
        record = store._issues[issue_id]
        record.artifact_type = "prd" if unit_id == prd_unit else "gap"
        store._persist()
    return backend


def test_doctor_absorb_asymmetry_passes_when_symmetric(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prd_unit = "094-prd-asymmetry-symmetric"
    gap_unit = "gap-261-asymmetry-symmetric"
    _seed_prd_gap_pair(
        root,
        cfg,
        prd_unit=prd_unit,
        gap_unit=gap_unit,
        prd_absorbs=[gap_unit],
        gap_absorbed_by=prd_unit,
    )
    result = doctor_absorb_asymmetry(root, cfg)
    assert result["verdict"] == "pass", result
    assert result.get("checks") == ["no-asymmetry"]


def test_doctor_absorb_asymmetry_fails_when_gap_back_pointer_without_prd_absorbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prd_unit = "094-prd-asymmetry-missing"
    gap_unit = "gap-263-asymmetry-missing"
    _seed_prd_gap_pair(
        root,
        cfg,
        prd_unit=prd_unit,
        gap_unit=gap_unit,
        prd_absorbs=[],
        gap_absorbed_by=prd_unit,
    )
    result = doctor_absorb_asymmetry(root, cfg)
    assert result["verdict"] == "fail", result
    assert result["error"] == "absorb-asymmetry"
    assert result["asymmetries"] == [
        {
            "gapUnitId": gap_unit,
            "prdUnitId": prd_unit,
            "reason": "gap-absorbed-by-without-prd-absorbs",
        }
    ]


def test_doctor_absorb_asymmetry_skips_gaps_without_absorbed_by(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prd_unit = "094-prd-asymmetry-unlinked"
    gap_unit = "gap-265-asymmetry-unlinked"
    _seed_prd_gap_pair(
        root,
        cfg,
        prd_unit=prd_unit,
        gap_unit=gap_unit,
        prd_absorbs=[],
        gap_absorbed_by=None,
    )
    result = doctor_absorb_asymmetry(root, cfg)
    assert result["verdict"] == "pass", result


def test_aggregate_doctor_surfaces_absorb_asymmetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg("absorb-asymmetry-aggregate")
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prd_unit = "094-prd-asymmetry-aggregate"
    gap_unit = "gap-264-asymmetry-aggregate"
    _seed_prd_gap_pair(
        root,
        cfg,
        prd_unit=prd_unit,
        gap_unit=gap_unit,
        prd_absorbs=None,
        gap_absorbed_by=prd_unit,
    )
    result = doctor(root, cfg)
    assert result["verdict"] == "fail", result
    assert result["action"] == "doctor-absorb-asymmetry"
    assert result["error"] == "absorb-asymmetry"
