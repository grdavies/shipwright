"""PRD 082 phase 3 — per-reason authority fixtures (R26) — Z,O,M,E,I."""

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
        ["git", "remote", "add", "origin", "https://github.com/acme/authority-fixture.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _issue_store_cfg(*, issues_provider: str = "github-issues", host_provider: str = "github") -> dict[str, Any]:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": issues_provider,
                "projectKey": "planning",
            }
        },
        "host": {"provider": host_provider},
    }


class TestZeroFallbackReasons:
    def test_online_has_no_substituted_backend_id(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        payload = decision.to_dict()
        assert "effective" not in payload
        assert decision.configured == "issue-store"
        assert decision.authorityState == "online"
        assert decision.writeDisposition == "accept"
        assert decision.cacheValidity == "fresh"
        assert decision.reason is None


class TestOneReasonEach:
    @pytest.mark.parametrize(
        ("reason", "authority_state", "write_disposition", "cache_validity"),
        [
            (par.REASON_KILL_SWITCH, "read-only", "refuse-substantive", "fresh"),
            (par.REASON_ISSUES_NONE_OR_UNSUPPORTED, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_ISSUES_NOT_SHIPPED, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_HOST_PROVIDER_NONE, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_BITBUCKET_ISSUES_UNAVAILABLE, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_OFFLINE_WITH_CACHE, "read-only", "refuse-substantive", "stale"),
            (par.REASON_STORE_UNAVAILABLE, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_IDENTITY_MISMATCH, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_AMBIGUOUS_AUTHORITY, "blocked", "refuse-substantive", "unavailable"),
            (par.REASON_PROJECTION_UNAVAILABLE, "online", "refuse-ledger", "fresh"),
        ],
    )
    def test_policy_matrix_maps_reason(
        self,
        reason: str,
        authority_state: str,
        write_disposition: str,
        cache_validity: str,
    ) -> None:
        policy = par.policy_for_reason(reason)
        assert policy["authorityState"] == authority_state
        assert policy["writeDisposition"] == write_disposition
        assert policy["cacheValidity"] == cache_validity


class TestManyConfiguredFallbacks:
    def test_kill_switch_is_read_only(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="operator", reason="rollback")["verdict"] == "ok"
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.authorityState == "read-only"
        assert decision.reason == par.REASON_KILL_SWITCH
        assert decision.writeDisposition == "refuse-substantive"
        assert ps.KILL_SWITCH_NOTICE in str(decision.guidance)

    def test_issues_provider_none_is_blocked(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(issues_provider="none")
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_ISSUES_NONE_OR_UNSUPPORTED

    def test_issues_provider_not_shipped_is_blocked(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(issues_provider="gitlab-issues")
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_ISSUES_NOT_SHIPPED

    def test_host_provider_none_is_blocked(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(host_provider="none")
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_HOST_PROVIDER_NONE


class TestBoundariesBitbucketGuidance:
    def test_bitbucket_guidance_retained(self, tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import subprocess

        subprocess.run(
            ["git", "remote", "add", "origin", "https://bitbucket.org/acme/authority-fixture.git"],
            cwd=tmp_git_repo,
            check=True,
            capture_output=True,
        )
        cfg = _issue_store_cfg(issues_provider="none", host_provider="bitbucket")
        _write_cfg(tmp_git_repo, cfg)
        monkeypatch.setattr(ps, "bitbucket_host_active", lambda _root, _cfg: True)
        decision = pa.resolve_authority(tmp_git_repo, cfg)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_BITBUCKET_ISSUES_UNAVAILABLE
        assert decision.guidance == ps.BITBUCKET_ISSUE_STORE_GUIDANCE


class TestErrorPaths:
    def test_identity_mismatch_blocks(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, identity_mismatch=True)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_IDENTITY_MISMATCH

    def test_ambiguous_authority_blocks(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, ambiguous=True)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_AMBIGUOUS_AUTHORITY

    def test_offline_without_cache_is_store_unavailable(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, offline=True, cache_available=False)
        assert decision.authorityState == "blocked"
        assert decision.reason == par.REASON_STORE_UNAVAILABLE

    def test_offline_with_cache_is_stale_reads(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, offline=True, cache_available=True)
        assert decision.authorityState == "read-only"
        assert decision.cacheValidity == "stale"
        assert decision.reason == par.REASON_OFFLINE_WITH_CACHE

    def test_projection_unavailable_uses_refuse_ledger(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        decision = pa.resolve_authority(tmp_git_repo, cfg, projection_available=False)
        assert decision.authorityState == "online"
        assert decision.writeDisposition == "refuse-ledger"
        assert decision.reason == par.REASON_PROJECTION_UNAVAILABLE
