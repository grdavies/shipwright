"""PRD 082 phase 8 — per-write-class disposition fixtures (R26) — Z,O,M,E,S,I."""

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
import planning_authority_reasons as par
import planning_backend_control as pbc
import planning_deliver_gate as pdg
import planning_gap_capture as pgc
import planning_progress as pp
import planning_projection_ledger as ppl
import planning_refusal_ledger as prl
import planning_store as ps
from closeout_ci import enforce_closeout_authority


def _write_cfg(repo: Path, cfg: dict[str, Any]) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _seed_remote(repo: Path) -> None:
    subprocess.run(
        ["git", "remote", "add", "origin", "https://github.com/acme/write-disposition-fixture.git"],
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
            },
            "refusalLedger": {
                "path": ".cursor/sw-refusal-ledger",
                "ttlSeconds": 2_592_000,
                "maxSizeBytes": 52_428_800,
            },
        },
        "host": {"provider": "github"},
    }


@pytest.fixture(autouse=True)
def _clear_write_log() -> None:
    pa.clear_backend_write_log()
    yield
    pa.clear_backend_write_log()


class TestSubstantiveWriteBlocks:
    def test_substantive_refusal_blocks_deliver_gate(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        assert pbc.cmd_disable(tmp_git_repo, set_by="fixture", reason="test")["verdict"] == "ok"
        with pytest.raises(SystemExit) as exc:
            pdg.write_disposition_gate(tmp_git_repo, phase_slug="phase-a")
        assert exc.value.code == pdg.GATE_FAIL_EXIT


class TestProjectionRefuseLedger:
    def test_projection_ledgers_and_marks_dirty_without_blocking(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        gi = tmp_git_repo / ".gitignore"
        gi.write_text(".cursor/**\n", encoding="utf-8")
        ppl.set_projection_dirty(tmp_git_repo, reason=par.REASON_PROJECTION_UNAVAILABLE)
        content = pgc.build_enriched_gap_content(
            unit_id="gap-001-test",
            title="projection fixture",
            problem="projection unavailable",
            context="fixture",
        )
        out = pgc.store_put_gap(
            tmp_git_repo,
            "gap-001-test",
            "docs/planning/gap/gap-001-test/gap-001-test.md",
            content,
            skip_enrichment=False,
        )
        assert out["verdict"] == "ok"
        assert out["disposition"] == "refuse-ledger"
        assert out.get("nonBlocking") is True
        assert len(prl.list_refusals(tmp_git_repo)) >= 1


class TestProgressLocalOnly:
    def test_progress_write_lands_in_run_directory(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        _write_cfg(tmp_git_repo, _issue_store_cfg())
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setenv("SW_PHASE_SLUG", "fixture-phase")
        try:
            out = pp.write_local_progress_state(
                tmp_git_repo,
                "3",
                {"action": "phase-done", "label": "sw:phase:3:done"},
            )
        finally:
            monkeypatch.undo()
        assert out["verdict"] == "ok"
        assert out["disposition"] == "local-only"
        assert out["authoritative"] is False
        path = Path(out["path"])
        assert path.is_file()
        assert ".cursor/sw-deliver-runs/fixture-phase/" in str(path)


class TestMidPhaseTransition:
    def test_mid_phase_transition_halts_with_resume(self, tmp_git_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        pdg.write_authority_pin(
            tmp_git_repo,
            "phase-b",
            {
                "writeDisposition": "accept",
                "authorityState": "online",
                "configured": "issue-store",
            },
        )

        def _degraded(_root: Path) -> dict[str, Any]:
            return {
                "configured": "issue-store",
                "authorityState": "read-only",
                "writeDisposition": "refuse-substantive",
                "cacheValidity": "stale",
                "reason": par.REASON_KILL_SWITCH,
            }

        monkeypatch.setattr(pdg, "resolve_deliver_authority", _degraded)
        with pytest.raises(SystemExit) as exc:
            pdg.write_disposition_gate(tmp_git_repo, phase_slug="phase-b")
        assert exc.value.code == pdg.GATE_FAIL_EXIT


class TestCloseoutOverrideBound:
    def test_closeout_cannot_upgrade_read_only_authority(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        pbc.cmd_disable(tmp_git_repo, set_by="fixture", reason="test")
        refusal = enforce_closeout_authority(tmp_git_repo, cfg)
        assert refusal is not None
        assert refusal["error"] == "closeout-authority-refused"
        assert refusal.get("resumeCommand")


class TestBackendOverrideNoUpgrade:
    def test_per_call_override_does_not_upgrade_authority(self, tmp_git_repo: Path) -> None:
        _seed_remote(tmp_git_repo)
        cfg = _issue_store_cfg()
        _write_cfg(tmp_git_repo, cfg)
        base = pa.resolve_authority(tmp_git_repo, cfg, offline=True, cache_available=False)
        overridden = pa.resolve_authority(tmp_git_repo, cfg, override="issue-store", offline=True, cache_available=False)
        assert base.writeDisposition == "refuse-substantive"
        assert overridden.writeDisposition == "refuse-substantive"
        assert not pa.substantive_deliver_allowed(overridden)
