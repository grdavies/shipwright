"""PRD 082 phase 4 — resolve-backend authority cutover fixtures (R26) — Z,O,E,S,I."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_authority as pa
import planning_authority_reasons as par
import planning_backend_control as pbc
import planning_backend_write_lint as pbl
import planning_store as ps


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _seed_remote(repo: Path) -> None:
    import subprocess

    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/resolve-backend.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


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


class TestZeroSubstitution:
    def test_resolution_reports_only_configured_id(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
        assert resolved["configured"] == "issue-store"
        assert resolved["backend"] == "issue-store"
        assert resolved["effective"] == "issue-store"
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.configured == resolved["configured"]


class TestOneIdentityMismatch:
    def test_identity_mismatch_blocks_reads(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
        resolved = {
            **resolved,
            "reason": par.REASON_IDENTITY_MISMATCH,
            "authorityState": "blocked",
        }
        blocked = ps.authority_io_block(resolved, operation="read")
        assert blocked is not None
        assert blocked["error"] == "identity-mismatch"

    def test_identity_mismatch_blocks_writes(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, identity_mismatch=True)
        assert decision.reason == par.REASON_IDENTITY_MISMATCH
        result = pa.apply_write_disposition(decision)
        assert result["verdict"] == "refused"
        resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
        resolved = {**resolved, "reason": par.REASON_IDENTITY_MISMATCH, "authorityState": "blocked"}
        assert ps.authority_io_block(resolved, operation="write") is not None


class TestManyKillSwitchSemantics:
    def test_disable_record_keeps_configured_without_substitution(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="rollback")["verdict"] == "ok"
        resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
        assert resolved["configured"] == "issue-store"
        assert resolved["effective"] == "issue-store"
        assert resolved.get("killSwitch") is True
        assert resolved["authorityState"] == "read-only"


class TestBoundariesExplicitOverride:
    def test_override_preserves_configured_backend(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="rollback")["verdict"] == "ok"
        resolved = ps.resolve_effective_backend(tmp_git_repo, cfg, override="issue-store")
        assert resolved["configured"] == "issue-store"
        assert resolved["effective"] == "issue-store"


class TestIntegrationLintFixture:
    def test_lint_fails_substituted_id_write_path(self, tmp_git_repo: Path) -> None:
        fixture_dir = tmp_git_repo / "scripts" / "fixture_backend_write_lint"
        fixture_dir.mkdir(parents=True)
        bad = fixture_dir / "substituted_write.py"
        bad.write_text(
            "import planning_authority as pa\n\n"
            "def bad_write(decision):\n"
            "    pa.record_backend_write('in-repo-public', configured='issue-store')\n",
            encoding="utf-8",
        )
        findings = pbl.scan_file(bad, rel="scripts/fixture_backend_write_lint/substituted_write.py")
        assert findings
        assert any(item.entry_point == "record_backend_write" for item in findings)
        assert any("in-repo-public" in item.detail for item in findings)

    def test_repo_lint_passes_without_substitution(self, tmp_path: Path) -> None:
        repo = tmp_path / "clean"
        (repo / "scripts").mkdir(parents=True)
        (repo / "scripts" / "good.py").write_text(
            "import planning_authority as pa\n\n"
            "def good_write(decision):\n"
            "    pa.record_backend_write(decision.configured, configured=decision.configured)\n",
            encoding="utf-8",
        )
        assert pbl.lint_repo(repo)["verdict"] == "pass"
