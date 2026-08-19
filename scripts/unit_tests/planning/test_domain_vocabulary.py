"""Domain vocabulary store + divergence tests (PRD 280 R9/R10/R17)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from domain_vocabulary import (  # noqa: E402
    check_divergence,
    get_term,
    put_term,
    validate_term,
    vocabulary_body_path,
)

DOMAIN_VOCAB_CLI = REPO_ROOT / "scripts" / "domain_vocabulary.py"
ACCOUNT_TERM = {
    "canonicalName": "Account",
    "definition": "Billing entity for a customer organization.",
    "aliases": ["customer account"],
    "forbiddenAliases": ["tenant", "workspace"],
    "status": "active",
    "introducedBy": "prd-280",
}


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "vocab-280") -> dict:
    return {
        "version": 1,
        "planning": {
            "intelligence": {"vocabulary": {"strictMode": False}},
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "hierarchy": {"epicSubIssues": True},
            },
        },
        "host": {"provider": "github"},
    }


def _run_cli(argv: list[str], *, repo_root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(DOMAIN_VOCAB_CLI), "--root", str(repo_root), *argv],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )


def test_term_schema_validation_rejects_missing_definition() -> None:
    with pytest.raises(SystemExit):
        validate_term({"canonicalName": "Account"})


def test_issue_store_put_get_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R7 — vocabulary put/get via issue-store fixture."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_issue_store_cfg()), encoding="utf-8"
    )

    put = put_term(root, "account", ACCOUNT_TERM)
    assert put["verdict"] == "pass"
    assert put["unitId"] == "vocab-account"
    assert put["bodyPath"] == vocabulary_body_path("account")
    assert not (root / "docs" / "planning" / "vocabulary" / "account.md").exists()

    got = get_term(root, "account")
    assert got["verdict"] == "pass"
    assert got["term"]["canonicalName"] == "Account"
    assert "tenant" in got["term"]["forbiddenAliases"]


def test_account_tenant_workspace_fixture_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R9 — triplet divergence is advisory (warn) by default."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_issue_store_cfg()), encoding="utf-8"
    )
    put_term(root, "account", ACCOUNT_TERM)

    prd_text = (
        "The PRD uses account for billing, but legacy code still says tenant "
        "and the public API exposes workspace identifiers."
    )
    result = check_divergence(root, text=prd_text, strict_mode=False)
    assert result["verdict"] == "pass"
    assert result["maxSeverity"] == "warn"
    concepts = [item["concept"] for item in result["divergence"]]
    assert "customer-entity" in concepts
    surfaces = {
        occ["surface"]
        for item in result["divergence"]
        for occ in item.get("occurrences") or []
        if occ.get("source") == "text"
    }
    assert {"account", "tenant", "workspace"}.issubset(surfaces)


def test_strict_mode_blocks_on_error_severity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R10/D4 — strictMode fail-closed on error-severity divergence."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    cfg["planning"]["intelligence"]["vocabulary"]["strictMode"] = True
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    put_term(root, "account", ACCOUNT_TERM)

    prd_text = "Operators manage account, tenant, and workspace records in one screen."
    result = check_divergence(root, text=prd_text)
    assert result["verdict"] == "fail"
    assert result["maxSeverity"] == "error"
    assert result.get("error") == "vocabulary-divergence-strict"

    cli = _run_cli(
        [
            "check-divergence",
            "--text",
            prd_text,
            "--strict",
        ],
        repo_root=root,
    )
    assert cli.returncode == 20
    payload = json.loads(cli.stdout)
    assert payload["verdict"] == "fail"


def test_cli_subcommands_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R8 — put/get/list/check CLI surface."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    (root / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_issue_store_cfg()), encoding="utf-8"
    )

    term_json = json.dumps(ACCOUNT_TERM)
    put = _run_cli(["put-term", "--slug", "account", "--json", term_json], repo_root=root)
    assert put.returncode == 0
    put_payload = json.loads(put.stdout)
    assert put_payload["action"] == "put-term"

    got = _run_cli(["get-term", "--slug", "account"], repo_root=root)
    assert got.returncode == 0
    assert json.loads(got.stdout)["term"]["canonicalName"] == "Account"

    listed = _run_cli(["list-terms"], repo_root=root)
    assert listed.returncode == 0
    listed_payload = json.loads(listed.stdout)
    assert listed_payload["count"] >= 1
    assert any(item["slug"] == "account" for item in listed_payload["terms"])

    div = _run_cli(
        [
            "check-divergence",
            "--text",
            "account and tenant naming drift",
        ],
        repo_root=root,
    )
    assert div.returncode == 0
    div_payload = json.loads(div.stdout)
    assert div_payload["action"] == "check-divergence"
    assert (root / ".cursor" / "sw-vocabulary-divergence" / "last.json").is_file()
