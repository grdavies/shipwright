"""PRD 080 phase 15 — disable record scoping, visibility, and doctor surfacing (R8)."""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_backend_control as pbc
import planning_store as ps


def _issue_store_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": "planning",
            }
        },
        "host": {"provider": "github"},
    }


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _init_second_repo(base: Path, remote: str, name: str) -> Path:
    repo = base / name
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "sw-test@example.com"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Shipwright Test"], cwd=repo, check=True, capture_output=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", remote], cwd=repo, check=True, capture_output=True)
    return repo


def test_record_scoped_to_one_repository_leaves_second_unaffected(tmp_path: Path) -> None:
    repo_a = _init_second_repo(tmp_path, "https://github.com/acme/repo-a.git", "repo-a")
    repo_b = _init_second_repo(tmp_path, "https://github.com/acme/repo-b.git", "repo-b")
    _write_cfg(repo_a, _issue_store_cfg())
    _write_cfg(repo_b, _issue_store_cfg())
    assert pbc.cmd_disable(repo_a, set_by="operator", reason="repo-a rollback")["verdict"] == "ok"
    assert ps.resolve_effective_backend(repo_a, _issue_store_cfg()).get("killSwitch") is True
    assert ps.resolve_effective_backend(repo_b, _issue_store_cfg()).get("killSwitch") is None


def test_list_records_offline(tmp_git_repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/list-fixture.git"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    _write_cfg(tmp_git_repo, _issue_store_cfg())
    assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="offline list")["verdict"] == "ok"
    listed = pbc.list_disable_records(tmp_git_repo)
    assert listed["verdict"] == "ok"
    assert listed["offline"] is True
    active = [row for row in listed["records"] if row.get("currentRepo")]
    assert len(active) == 1
    assert active[0]["setBy"] == "operator"
    assert active[0]["reason"] == "offline list"
    assert active[0]["setAt"]


def test_doctor_surfaces_disable_record(tmp_git_repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/doctor-fixture.git"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    _write_cfg(tmp_git_repo, _issue_store_cfg())
    assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="doctor surface")["verdict"] == "ok"
    doctor = importlib.import_module("planning-doctor")
    finding = doctor.backend_disable_record_finding(tmp_git_repo)
    assert finding is not None
    assert finding["check"] == "backend-disable-record"
    assert finding["reason"] == "doctor surface"


def test_forced_fallback_refused_for_private_tier_pending(tmp_git_repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/private-fixture.git"],
        cwd=tmp_git_repo,
        check=True,
        capture_output=True,
    )
    cfg = _issue_store_cfg()
    _write_cfg(tmp_git_repo, cfg)
    private_doc = tmp_git_repo / "docs" / "prds" / "099-private" / "099-private-prd.md"
    private_doc.parent.mkdir(parents=True, exist_ok=True)
    private_doc.write_text(
        "---\nvisibility: private\n---\n# private pending\n",
        encoding="utf-8",
    )
    out = pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="should refuse")
    assert out["verdict"] == "fail"
    assert out["error"] == "private-tier-pending-refuses-forced-fallback"
    assert ps.resolve_effective_backend(tmp_git_repo, cfg).get("killSwitch") is None
