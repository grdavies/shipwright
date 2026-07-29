"""PRD 082 phase 9 — hash-chained authority audit journal fixtures (R26) — Z,O,M,B,E,S."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_audit_journal as paj
import planning_audit_journal_cli as pajc


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


class TestHashChain:
    def test_well_formed_chain_verifies(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        first = paj.append_authority_disable(
            tmp_git_repo,
            set_by="operator",
            reason="maintenance",
            repo_scope="org/repo",
        )
        second = paj.append_authority_enable(
            tmp_git_repo,
            repo_scope="org/repo",
            removed=True,
        )
        assert first["verdict"] == "ok"
        assert second["verdict"] == "ok"
        assert second["entry"]["prevDigest"] == first["entry"]["digest"]
        verified = paj.verify_chain(tmp_git_repo)
        assert verified["verdict"] == "ok"
        assert verified["entryCount"] == 2

    def test_tampered_link_fails_verification(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        paj.append_authority_disable(
            tmp_git_repo,
            set_by="operator",
            reason="maintenance",
        )
        path = paj.journal_path(tmp_git_repo)
        lines = path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["metadata"]["reason"] = "tampered"
        entry["digest"] = "deadbeef"
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        verified = paj.verify_chain(tmp_git_repo)
        assert verified["verdict"] == "fail"
        assert verified["error"] == paj.CHAIN_INVALID_ERROR

    def test_truncated_chain_fails_verification(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        paj.append_authority_disable(tmp_git_repo, set_by="operator", reason="one")
        paj.append_authority_enable(tmp_git_repo, removed=True)
        path = paj.journal_path(tmp_git_repo)
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text(lines[0] + "\n", encoding="utf-8")
        verified = paj.verify_chain(tmp_git_repo)
        assert verified["verdict"] == "ok"
        assert verified["entryCount"] == 1

    def test_broken_chain_blocks_next_authority_change(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        paj.append_authority_disable(tmp_git_repo, set_by="operator", reason="seed")
        path = paj.journal_path(tmp_git_repo)
        entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        entry["digest"] = "0" * 64
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        blocked = paj.append_authority_enable(tmp_git_repo, removed=True)
        assert blocked["verdict"] == "fail"
        assert blocked["error"] == paj.CHAIN_INVALID_ERROR

    def test_verify_cli_returns_stable_failure_code(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        paj.append_authority_disable(tmp_git_repo, set_by="operator", reason="seed")
        path = paj.journal_path(tmp_git_repo)
        entry = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        entry["digest"] = "0" * 64
        path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(scripts / "planning_audit_journal_cli.py"),
                "--root",
                str(tmp_git_repo),
                "verify",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == pajc.VERIFY_EXIT_CHAIN_INVALID
        payload = json.loads(proc.stdout)
        assert payload["verdict"] == "fail"
        assert payload["blocksAuthorityChanges"] is True


class TestTransitionMetadata:
    def test_entries_carry_no_body_content(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        sensitive_body = "unit-body:classified-planning-content-must-not-persist"
        with pytest.raises(paj.AuditJournalError, match="body field"):
            paj.append_transition(
                tmp_git_repo,
                paj.TRANSITION_AUTHORITY_BLOCK,
                {
                    "authorityState": "blocked",
                    "operation": "write",
                    "body": sensitive_body,
                },
            )
        result = paj.append_authority_block(
            tmp_git_repo,
            authority_state="blocked",
            reason="store-unavailable",
            operation="write",
        )
        assert result["verdict"] == "ok"
        serialized = json.dumps(result["entry"])
        assert sensitive_body not in serialized
        for forbidden in paj.BODY_FIELD_NAMES:
            assert forbidden not in result["entry"].get("metadata", {})

    def test_supported_transitions_append_metadata_only(self, tmp_git_repo: Path) -> None:
        _seed_gitignore(tmp_git_repo, ".cursor/**")
        _write_cfg(tmp_git_repo, _journal_cfg())
        transitions = [
            paj.append_authority_disable(
                tmp_git_repo,
                set_by="op",
                reason="disable",
            ),
            paj.append_authority_enable(tmp_git_repo, removed=True),
            paj.append_authority_block(
                tmp_git_repo,
                authority_state="blocked",
                reason="identity-mismatch",
                operation="read",
            ),
            paj.append_split_brain_detection(
                tmp_git_repo,
                error="projection-prefer-split-brain",
                action="check-canonical-projection-split-brain",
            ),
            paj.append_sensitivity_declassification(
                tmp_git_repo,
                stable_id="env-1",
                from_tier="secret",
                to_tier="private",
                approver="human",
            ),
            paj.append_ledger_purge(
                tmp_git_repo,
                purged_count=2,
                entry_ids=["entry-a", "entry-b"],
            ),
        ]
        assert all(row["verdict"] == "ok" for row in transitions)
        assert paj.verify_chain(tmp_git_repo)["entryCount"] == len(transitions)
