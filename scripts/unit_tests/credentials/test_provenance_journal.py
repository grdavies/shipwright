"""Provenance journal tests (PRD 080 4.4 / R7)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from credentials.provenance_journal import (
    ProvenanceEvent,
    ProvenanceJournalError,
    append_entry,
    contains_secret_material,
    load_journal,
)


def _prepare_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


class TestEmptyJournal:
    def test_empty_journal_loads(self, tmp_path: Path) -> None:
        journal = tmp_path / "credential-provenance.journal.jsonl"
        _prepare_file(journal)
        assert load_journal(path=journal, skip_integrity=True) == []


class TestOneApproval:
    def test_one_pairing_approval_appends_metadata(self, tmp_path: Path) -> None:
        journal = tmp_path / "credential-provenance.journal.jsonl"
        _prepare_file(journal)
        entry = append_entry(
            ProvenanceEvent.PAIRING_APPROVAL,
            {
                "credentialRef": "github-work",
                "projectId": "proj-1",
                "remote": "https://github.com/owner/repo.git",
            },
            path=journal,
            skip_integrity=True,
        )
        assert entry.event == "pairing_approval"
        loaded = load_journal(path=journal, skip_integrity=True)
        assert len(loaded) == 1
        assert loaded[0].metadata["credentialRef"] == "github-work"


class TestManyEvents:
    def test_many_events_remain_append_only(self, tmp_path: Path) -> None:
        journal = tmp_path / "credential-provenance.journal.jsonl"
        _prepare_file(journal)
        append_entry(
            ProvenanceEvent.PAIRING_APPROVAL,
            {"credentialRef": "github-work", "projectId": "proj-1", "remote": "origin"},
            path=journal,
            skip_integrity=True,
        )
        append_entry(
            ProvenanceEvent.SCOPE_CHANGE,
            {"credentialRef": "github-work", "field": "allowedRepos", "value": "owner/repo"},
            path=journal,
            skip_integrity=True,
        )
        append_entry(
            ProvenanceEvent.ROTATION,
            {"credentialRef": "github-work", "backend": "github_cli"},
            path=journal,
            skip_integrity=True,
        )
        loaded = load_journal(path=journal, skip_integrity=True)
        assert [item.event for item in loaded] == [
            "pairing_approval",
            "scope_change",
            "rotation",
        ]
        assert journal.read_text(encoding="utf-8").count("\n") == 3


class TestSecretBearingEntry:
    def test_secret_bearing_entry_refuses_write(self, tmp_path: Path) -> None:
        journal = tmp_path / "credential-provenance.journal.jsonl"
        _prepare_file(journal)
        secret_value = "ghp_" + ("a" * 36)
        assert contains_secret_material(secret_value)
        with pytest.raises(ProvenanceJournalError) as exc:
            append_entry(
                ProvenanceEvent.ROTATION,
                {"credentialRef": "github-work", "note": secret_value},
                path=journal,
                skip_integrity=True,
            )
        assert exc.value.code == "provenance-secret-bearing"
        assert load_journal(path=journal, skip_integrity=True) == []

    def test_high_entropy_kv_refuses_write(self, tmp_path: Path) -> None:
        journal = tmp_path / "credential-provenance.journal.jsonl"
        _prepare_file(journal)
        with pytest.raises(ProvenanceJournalError) as exc:
            append_entry(
                ProvenanceEvent.ROTATION,
                {
                    "credentialRef": "github-work",
                    "detail": "token=sk_test_fixture_allowlisted_secret_scan_0123456789",
                },
                path=journal,
                skip_integrity=True,
            )
        assert exc.value.code == "provenance-secret-bearing"
