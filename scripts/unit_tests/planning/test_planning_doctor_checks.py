"""PRD 082 R34 — unified doctor inspection fixtures (Z,O,M,E,S,I)."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import memory_doctor_checks as mdc
import planning_audit_journal as paj
import planning_doctor_ledger as pdl
import planning_projection_ledger as ppl

MODULE_NAME = "planning-doctor"


def _load_doctor():
    return importlib.import_module(MODULE_NAME)


def _write_cfg(repo: Path, cfg: dict) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _seed_gitignore(repo: Path, *patterns: str) -> None:
    gi = repo / ".gitignore"
    existing = gi.read_text(encoding="utf-8") if gi.is_file() else ""
    merged = sorted({line.strip() for line in (existing.splitlines() + list(patterns)) if line.strip()})
    gi.write_text("\n".join(merged) + "\n", encoding="utf-8")


def _journal_cfg(path: str = ".cursor/sw-authority-audit-journal") -> dict:
    return {"planning": {"auditJournal": {"path": path}}}


def _ledger_cfg(path: str = ".cursor/sw-refusal-ledger") -> dict:
    return {"planning": {"refusalLedger": {"path": path}}}


def _check_by_name(checks: list[dict], name: str) -> dict:
    for check in checks:
        if check.get("check") == name:
            return check
    raise AssertionError(f"missing check {name!r}: {[c.get('check') for c in checks]}")


class TestDoctorCheckShape:
    def test_each_check_has_status_and_optional_failure_code(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, {**_journal_cfg(), **_ledger_cfg()})
        doctor = _load_doctor()
        out = doctor.doctor(tmp_git_repo, sweep=False)
        assert out["verdict"] in {"ok", "degraded", "fail"}
        for check in out["checks"]:
            assert check.get("status") in {"ok", "pass", "warn", "fail", "advisory", "drift", "action-required", "degraded"}
            if check.get("status") == "fail":
                assert check.get("failureCode") or check.get("error")
                assert check.get("remediation")


class TestLedgerDoctorChecks:
    def test_broken_audit_chain_fails_with_stable_code(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        paj.append_authority_disable(tmp_git_repo, set_by="operator", reason="seed")
        path = paj.journal_path(tmp_git_repo)
        entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        entry["digest"] = "0" * 64
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        check = pdl.check_audit_journal_chain(tmp_git_repo, _journal_cfg())
        assert check["status"] == "fail"
        assert check["failureCode"] == pdl.FAILURE_AUDIT_JOURNAL_CHAIN
        assert check.get("remediation")

    def test_dirty_projection_fails_with_stable_code(self, tmp_git_repo: Path) -> None:
        ppl.set_projection_dirty(tmp_git_repo, reason="doctor-fixture")
        check = pdl.check_projection_dirty(tmp_git_repo)
        assert check["status"] == "fail"
        assert check["failureCode"] == pdl.FAILURE_PROJECTION_DIRTY
        assert check.get("remediation")

    def test_non_gitignored_ledger_fails_with_stable_code(self, tmp_git_repo: Path) -> None:
        _write_cfg(tmp_git_repo, _ledger_cfg())
        ledger_dir = tmp_git_repo / ".cursor" / "sw-refusal-ledger"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        check = pdl.check_refusal_ledger(tmp_git_repo, _ledger_cfg())
        assert check["status"] == "fail"
        assert check["failureCode"] == pdl.FAILURE_LEDGER_NOT_GITIGNORED
        assert check.get("remediation")


class TestMemoryDoctorChecks:
    def test_alias_collision_fails_with_stable_code(self, tmp_git_repo: Path) -> None:
        store = tmp_git_repo / ".cursor" / "sw-memory" / "memories"
        store.mkdir(parents=True)
        first = store / "alpha.md"
        second = store / "beta.md"
        first.write_text(
            "---\nstableId: id-a\ncategory: learning\nstatus: active\npermalink: shared-alias\n---\nbody\n",
            encoding="utf-8",
        )
        second.write_text(
            "---\nstableId: id-b\ncategory: learning\nstatus: active\npermalink: shared-alias\n---\nbody\n",
            encoding="utf-8",
        )
        check = mdc.check_alias_collisions(tmp_git_repo)
        assert check["status"] == "fail"
        assert check["failureCode"] == mdc.FAILURE_ALIAS_COLLISION
        assert check.get("remediation")

    def test_clean_alias_index_passes(self, tmp_git_repo: Path) -> None:
        check = mdc.check_alias_collisions(tmp_git_repo)
        assert check["status"] == "pass"


class TestUnifiedDoctorIntegration:
    def test_doctor_surfaces_identity_and_authority_sections(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, {**_journal_cfg(), **_ledger_cfg()})
        doctor = _load_doctor()
        out = doctor.doctor(tmp_git_repo, sweep=False)
        names = {check.get("check") for check in out["checks"]}
        assert "repository-identity" in names
        assert "credential-probe" in names
        assert "planning-authority-state" in names
        assert "refusal-ledger" in names
        assert "projection-dirty" in names
        assert "authority-audit-journal-chain" in names
        assert "memory-source-of-truth" in names

    def test_doctor_fails_on_broken_audit_chain(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, {**_journal_cfg(), **_ledger_cfg()})
        paj.append_authority_disable(tmp_git_repo, set_by="operator", reason="seed")
        path = paj.journal_path(tmp_git_repo)
        entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        entry["digest"] = "0" * 64
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        doctor = _load_doctor()
        out = doctor.doctor(tmp_git_repo, sweep=False)
        chain = _check_by_name(out["checks"], "authority-audit-journal-chain")
        assert chain["status"] == "fail"
        assert out["verdict"] == "fail"
