"""PRD 082 phase 3 — no substituted-backend write fixtures (R26) — Z,O,M,E,I."""

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
import planning_store as ps


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _seed_remote(repo: Path) -> None:
    import subprocess

    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/no-sub-fixture.git"],
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


def _file_store_cfg() -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "in-repo-public",
                "projectKey": "planning",
            }
        }
    }


def _non_configured_writes(log: list[dict[str, Any]], configured: str) -> list[dict[str, Any]]:
    return [entry for entry in log if entry.get("backend") != configured]


@pytest.fixture(autouse=True)
def _clear_write_log() -> None:
    pa.clear_backend_write_log()
    yield
    pa.clear_backend_write_log()


class TestZeroNonConfiguredWrites:
    @pytest.mark.parametrize(
        "resolve_kwargs",
        [
            {},
            {"identity_mismatch": True},
            {"ambiguous": True},
            {"offline": True, "cache_available": False},
            {"offline": True, "cache_available": True},
            {"projection_available": False},
        ],
    )
    def test_runtime_signals_never_write_substituted_backend(
        self,
        tmp_git_repo: Path,
        resolve_kwargs: dict[str, Any],
    ) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, **resolve_kwargs)
        result = pa.apply_write_disposition(decision, write_class="substantive")
        assert _non_configured_writes(pa.backend_write_log(), decision.configured) == []
        if result["verdict"] == "ok":
            assert result["backend"] == decision.configured


class TestOneConfiguredBackend:
    def test_kill_switch_keeps_configured_id_without_substitution(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="rollback")["verdict"] == "ok"
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.configured == "issue-store"
        assert "effective" not in decision.to_dict()
        pa.apply_write_disposition(decision)
        assert _non_configured_writes(pa.backend_write_log(), "issue-store") == []

    def test_in_repo_public_writes_only_when_configured(self, tmp_git_repo: Path) -> None:
        cfg = _file_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.configured == "in-repo-public"
        pa.apply_write_disposition(decision)
        assert all(entry["backend"] == "in-repo-public" for entry in pa.backend_write_log())


class TestManyFallbackReasons:
    @pytest.mark.parametrize(
        "reason",
        [
            par.REASON_ISSUES_NONE_OR_UNSUPPORTED,
            par.REASON_ISSUES_NOT_SHIPPED,
            par.REASON_HOST_PROVIDER_NONE,
        ],
    )
    def test_blocked_fallbacks_record_zero_substituted_writes(
        self,
        tmp_git_repo: Path,
        reason: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        monkeypatch.setattr(par, "resolve_fallback_reason", lambda *_a, **_k: reason)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        pa.apply_write_disposition(decision)
        assert decision.configured == "issue-store"
        assert _non_configured_writes(pa.backend_write_log(), decision.configured) == []


class TestBoundariesExplicitOverride:
    def test_explicit_override_does_not_substitute_configured_backend(
        self,
        tmp_git_repo: Path,
    ) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="rollback")["verdict"] == "ok"
        decision = pa.resolve_authority(tmp_git_repo, cfg, override="issue-store")
        assert decision.configured == "issue-store"
        assert decision.authorityState == "online"
        pa.apply_write_disposition(decision)
        assert _non_configured_writes(pa.backend_write_log(), "issue-store") == []


class TestIntegrationAuthorityContract:
    def test_resolve_effective_backend_matches_authority_contract(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="rollback")["verdict"] == "ok"
        resolved = ps.resolve_effective_backend(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert resolved["configured"] == decision.configured
        assert resolved["effective"] == decision.configured
        assert resolved["authorityState"] == decision.authorityState
