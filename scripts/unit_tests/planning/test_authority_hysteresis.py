"""PRD 082 phase 5 — hysteresis and multi-chunk fixtures (R26) — O,M,B,S,E."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_authority as pa
import planning_authority_probe as pap
import planning_authority_reasons as par
from planning_authority import AuthorityDecision


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _seed_remote(repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/hysteresis-fixture.git"],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _issue_store_cfg(*, probe: dict[str, Any] | None = None) -> dict[str, Any]:
    store: dict[str, Any] = {
        "backend": "issue-store",
        "issuesProvider": "github-issues",
        "projectKey": "planning",
    }
    if probe is not None:
        store["authorityProbe"] = probe
    return {"planning": {"store": store}, "host": {"provider": "github"}}


def _offline_decision(configured: str = "issue-store") -> AuthorityDecision:
    return AuthorityDecision(
        configured=configured,
        authorityState="read-only",
        reason=par.REASON_OFFLINE_WITH_CACHE,
        writeDisposition="refuse-substantive",
        cacheValidity="stale",
        guidance=None,
    )


def _online_decision(configured: str = "issue-store") -> AuthorityDecision:
    return AuthorityDecision(
        configured=configured,
        authorityState="online",
        reason=None,
        writeDisposition="accept",
        cacheValidity="fresh",
        guidance=None,
    )


class TestSingleProbeBlip:
    def test_single_blip_does_not_flip_state(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(probe={"failureThreshold": 3, "minDwellSeconds": 0})
        _write_cfg(tmp_git_repo, cfg)
        offline = _offline_decision()
        first = pap.apply_probe_result(tmp_git_repo, offline, cfg=cfg, probe_ok=False)
        second = pap.apply_probe_result(tmp_git_repo, offline, cfg=cfg, probe_ok=False)
        assert first.authorityState == "online"
        assert second.authorityState == "online"
        state = pap.load_state(tmp_git_repo)
        assert state["consecutiveFailures"] == 2
        assert state["authorityState"] == "online"


class TestHysteresisTransition:
    def test_consecutive_failures_flip_state(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(probe={"failureThreshold": 3, "minDwellSeconds": 0})
        _write_cfg(tmp_git_repo, cfg)
        offline = _offline_decision()
        for _ in range(2):
            pap.apply_probe_result(tmp_git_repo, offline, cfg=cfg, probe_ok=False)
        third = pap.apply_probe_result(tmp_git_repo, offline, cfg=cfg, probe_ok=False)
        assert third.authorityState == "read-only"
        transitions = pap.read_flap_transitions(tmp_git_repo)
        assert len(transitions) == 1
        assert transitions[0]["from"] == "online"
        assert transitions[0]["to"] == "read-only"
        assert transitions[0]["trigger"] == "degrade"

    def test_recovery_probe_precedes_return_to_online(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(
            probe={"failureThreshold": 1, "minDwellSeconds": 0, "recoverySuccesses": 1}
        )
        _write_cfg(tmp_git_repo, cfg)
        offline = _offline_decision()
        pap.apply_probe_result(tmp_git_repo, offline, cfg=cfg, probe_ok=False)
        state = pap.load_state(tmp_git_repo)
        assert state["authorityState"] == "read-only"
        assert state["pendingRecovery"] is True
        recovered = pap.apply_probe_result(tmp_git_repo, _online_decision(), cfg=cfg, probe_ok=True)
        assert recovered.authorityState == "online"
        transitions = pap.read_flap_transitions(tmp_git_repo)
        assert any(item.get("trigger") == "recovery" for item in transitions)


class TestOperationPinning:
    def test_operation_pin_resolves_once(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(probe={"failureThreshold": 1, "minDwellSeconds": 0})
        _write_cfg(tmp_git_repo, cfg)
        calls = {"count": 0}

        def raw_resolver() -> AuthorityDecision:
            calls["count"] += 1
            return _online_decision()

        with pap.operation_authority_pin(tmp_git_repo, cfg, raw_resolver=raw_resolver) as decision:
            assert decision.authorityState == "online"
            pinned = pap.resolve_pinned_authority(tmp_git_repo, cfg)
            assert pinned.authorityState == "online"
            again = pap.resolve_pinned_authority(tmp_git_repo, cfg)
            assert again.authorityState == "online"
        assert calls["count"] == 1

    def test_head_plus_overflow_chunk_write_is_atomic(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(probe={"failureThreshold": 1, "minDwellSeconds": 0})
        _write_cfg(tmp_git_repo, cfg)
        observed: list[str] = []

        def writer(chunk: str, decision: AuthorityDecision) -> str:
            observed.append(decision.authorityState)
            return f"{chunk}:{decision.writeDisposition}"

        result = pap.run_chunked_operation(
            tmp_git_repo,
            cfg,
            ["head", "overflow"],
            writer,
            raw_resolver=lambda: _online_decision(),
            probe_ok=True,
        )
        assert result["verdict"] == "ok"
        assert result["chunksCompleted"] == 2
        assert observed == ["online", "online"]

    def test_chunked_write_refuses_as_whole_when_degraded(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(probe={"failureThreshold": 1, "minDwellSeconds": 0})
        _write_cfg(tmp_git_repo, cfg)
        pap.apply_probe_result(tmp_git_repo, _offline_decision(), cfg=cfg, probe_ok=False)

        def writer(chunk: str, decision: AuthorityDecision) -> str:
            raise AssertionError("writer must not run when refused")

        result = pap.run_chunked_operation(
            tmp_git_repo,
            cfg,
            ["head", "overflow"],
            writer,
            raw_resolver=lambda: _offline_decision(),
            probe_ok=False,
        )
        assert result["verdict"] == "refused"
        assert result["chunksCompleted"] == 0


class TestDoctorFlapReporting:
    def test_flap_transitions_readable_by_doctor(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg(probe={"failureThreshold": 1, "minDwellSeconds": 0})
        _write_cfg(tmp_git_repo, cfg)
        pap.apply_probe_result(tmp_git_repo, _offline_decision(), cfg=cfg, probe_ok=False)
        report = pap.doctor_authority_flap_report(tmp_git_repo)
        assert report["verdict"] == "pass"
        assert report["action"] == "doctor-authority-flap"
        assert report["transitionCount"] == 1
        assert report["flapTransitions"][0]["to"] == "read-only"
