"""PRD 069 R2 — scoped absorb-pollution doctor avoids project-wide search on index hit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from issues_lib import FixtureIssuesStore
from planning_canonical import compose_issue_body, status_label
from planning_store import IssueStoreBackend, doctor_absorb_pollution


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

    with patch("planning_store.get_backend", side_effect=_fake_get_backend):
        with patch.object(backend._client, "issue_search", side_effect=_tracking_search):
            result = doctor_absorb_pollution(root, cfg, prd_unit_id=prd_unit)

    assert result["verdict"] == "pass", result
    assert result.get("prdUnitId") == prd_unit
    assert not any(call.get("artifact_type") == "prd" and "unit_id" not in call for call in search_calls)


def test_scoped_doctor_index_miss_uses_unit_scoped_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg("absorb-069-miss")
    (root / ".cursor/workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    project_key = cfg["planning"]["store"]["projectKey"]
    prd_unit = "069-prd-miss-index"
    fixture = root / ".cursor/hooks/state/issue-store-fixture.json"
    store = FixtureIssuesStore(fixture)
    prd_body = compose_issue_body(
        project_key,
        "prd",
        prd_unit,
        f"---\ntype: prd\nid: {prd_unit}\nstatus: complete\n---\n# PRD 069\n",
    )
    store.create(
        title="PRD 069",
        body=prd_body,
        labels=["sw:prd", f"sw:unit:{prd_unit}", status_label("complete")],
        project_key=project_key,
        artifact_type="prd",
        unit_id=prd_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps({"version": 1, "units": {}}),
        encoding="utf-8",
    )
    backend = IssueStoreBackend(root, cfg)
    search_calls: list[dict[str, Any]] = []
    original_search = backend._client.issue_search

    def _tracking_search(**kwargs: Any) -> list[Any]:
        search_calls.append(dict(kwargs))
        return original_search(**kwargs)

    def _fake_get_backend(_root: Path, _cfg: dict[str, Any], override: str | None = None) -> IssueStoreBackend:
        return backend

    with patch("planning_store.get_backend", side_effect=_fake_get_backend):
        with patch.object(backend._client, "issue_search", side_effect=_tracking_search):
            result = doctor_absorb_pollution(root, cfg, prd_unit_id=prd_unit)

    assert result["verdict"] == "pass", result
    assert any(
        call.get("unit_id") == prd_unit and call.get("artifact_type") == "prd"
        for call in search_calls
    )
    assert not any(
        call.get("artifact_type") == "prd" and "unit_id" not in call
        for call in search_calls
    )
