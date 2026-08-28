"""PRD 069 R2 — scoped absorb-pollution doctor avoids project-wide search on index hit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import pytest

from issues_lib import FixtureIssuesStore, IssueRecord
from planning_canonical import compose_issue_body, status_label
from planning_store import IssueStoreBackend, doctor_absorb_pollution
from planning_store_facade import _lookup_issue_record


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "absorb-069") -> dict[str, Any]:
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


def _fixture_prd(
    root: Path,
    cfg: dict[str, Any],
    *,
    prd_unit: str,
    complete: bool = True,
) -> tuple[IssueStoreBackend, str]:
    project_key = cfg["planning"]["store"]["projectKey"]
    slug = "surface-hygiene"
    prd_path = f"docs/prds/069-{slug}/{prd_unit}.md"
    labels = ["sw:prd", f"sw:unit:{prd_unit}"]
    if complete:
        labels.append(status_label("complete"))
    content = f"---\ntype: prd\nid: {prd_unit}\nstatus: complete\n---\n# PRD 069\n"
    backend = IssueStoreBackend(root, cfg)
    assert backend.put(prd_unit, prd_path, content).verdict == "ok"
    idx_path = root / ".cursor/hooks/state/issue-store-unit-index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    issue_id = index["units"][f"{project_key}:{prd_unit}"]
    return backend, issue_id


def _doctor_prd_record(prd_unit: str, *, absorbs: str | None = None) -> IssueRecord:
    absorbs_line = f"absorbs: {absorbs}\n" if absorbs else ""
    return IssueRecord(
        id=f"issue-{prd_unit}",
        number=69,
        title=prd_unit,
        body=(
            f"---\ntype: prd\nid: {prd_unit}\nstatus: complete\n"
            f"{absorbs_line}---\n# PRD 069\n"
        ),
        state="open",
        labels=["sw:prd", f"sw:unit:{prd_unit}", status_label("complete")],
        artifact_type="prd",
        unit_id=prd_unit,
    )


def test_scoped_doctor_index_hit_skips_project_wide_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prd_unit = "069-prd-surface-hygiene"
    backend, _issue_id = _fixture_prd(root, cfg, prd_unit=prd_unit, complete=True)
    search_calls: list[dict[str, Any]] = []
    original_search = backend._client.issue_search

    def _tracking_search(**kwargs: Any) -> list[Any]:
        search_calls.append(dict(kwargs))
        return original_search(**kwargs)

    def _fake_get_backend(_root: Path, _cfg: dict[str, Any], override: str | None = None) -> IssueStoreBackend:
        return backend

    with patch.dict(
        doctor_absorb_pollution.__globals__,
        {"get_backend": _fake_get_backend},
    ):
        with patch.object(backend._client, "issue_search", side_effect=_tracking_search):
            result = doctor_absorb_pollution(root, cfg, prd_unit_id=prd_unit)

    assert result["verdict"] == "pass", result
    assert result.get("prdUnitId") == prd_unit
    assert not any(call.get("artifact_type") == "prd" and "unit_id" not in call for call in search_calls)


def test_project_doctor_skips_closure_audit_for_prd_without_absorbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    backend = IssueStoreBackend(root, cfg)
    records = [
        _doctor_prd_record(f"{number:03d}-prd-unrelated-complete")
        for number in range(1, 131)
    ]

    audit = Mock()
    with patch.dict(
        doctor_absorb_pollution.__globals__,
        {
            "get_backend": Mock(return_value=backend),
            "audit_closure_completeness": audit,
        },
    ):
        with patch.object(backend._client, "issue_search", return_value=records) as search:
            result = doctor_absorb_pollution(root, cfg)

    assert result["verdict"] == "pass", result
    search.assert_called_once_with(project_key="absorb-069")
    audit.assert_not_called()


def test_project_doctor_audits_complete_prd_with_absorbs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    prd_unit = "069-prd-absorbing-complete"
    backend = IssueStoreBackend(root, cfg)
    record = _doctor_prd_record(prd_unit, absorbs="gap-123-open")

    def _audit_from_catalog(_root: Path, _cfg: dict[str, Any], _prd_unit: str) -> dict[str, Any]:
        assert _lookup_issue_record(backend, "tasks-not-present", "docs/prds/tasks-not-present.md") is None
        return {"openRemaining": ["gap-123-open"]}

    audit = Mock(side_effect=_audit_from_catalog)
    with patch.dict(
        doctor_absorb_pollution.__globals__,
        {
            "get_backend": Mock(return_value=backend),
            "audit_closure_completeness": audit,
        },
    ):
        with patch.object(backend._client, "issue_search", return_value=[record]) as search:
            result = doctor_absorb_pollution(root, cfg)

    assert result["verdict"] == "fail", result
    assert result["pollution"] == [
        {"prdUnitId": prd_unit, "openRemaining": "gap-123-open"}
    ]
    search.assert_called_once_with(project_key="absorb-069")
    audit.assert_called_once_with(root, cfg, prd_unit)
