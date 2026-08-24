"""PRD 327 R4 — Notion token and database scope probes (hermetic)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from planning_notion_client import probe_database, probe_token


def _write_cfg(root: Path, *, with_database: bool = True) -> None:
    issues: dict[str, str] = {"tokenEnv": "ISSUES_NOTION_TOKEN"}
    if with_database:
        issues["notionDatabaseId"] = "db-fixture-00000000000000000000000000000001"
    payload = {
        "planning": {
            "store": {
                "backend": "issue-store",
                "projectKey": "acme",
                "issuesProvider": "notion",
                "issues": issues,
            }
        }
    }
    (root / "workflow.config.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_probe_token_missing_advisory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_cfg(root)
    monkeypatch.delenv("ISSUES_NOTION_TOKEN", raising=False)
    result = probe_token(root, json.loads((root / "workflow.config.json").read_text()))
    assert result["verdict"] == "fail"
    assert result["error"] == "missing-token"
    finding = importlib.import_module("planning-doctor").classify_issue_store_probe(result)
    assert finding["check"] == "store-token-absent"
    blob = json.dumps(result)
    assert "Bearer " not in blob
    assert "ntn_" not in blob


def test_probe_database_fixture_ok(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_cfg(root)
    monkeypatch.setenv("SW_NOTION_PROBE_FIXTURE", "1")
    monkeypatch.setenv("ISSUES_NOTION_TOKEN", "fixture-token-not-logged")
    cfg = json.loads((root / "workflow.config.json").read_text())
    token_result = probe_token(root, cfg)
    assert token_result["verdict"] == "ok"
    db_result = probe_database(root, cfg)
    assert db_result["verdict"] == "ok"
    assert db_result.get("fixtureProbe") is True
    assert "fixture-token" not in json.dumps(db_result)


def test_probe_database_scope_refused_missing_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write_cfg(root, with_database=False)
    monkeypatch.setenv("SW_NOTION_PROBE_FIXTURE", "1")
    monkeypatch.setenv("ISSUES_NOTION_TOKEN", "fixture-token")
    cfg = json.loads((root / "workflow.config.json").read_text())
    result = probe_database(root, cfg)
    assert result["verdict"] == "fail"
    assert result["error"] == "missing-database-id"
