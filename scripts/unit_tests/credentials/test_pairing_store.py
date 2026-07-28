"""Pairing refusal tests (PRD 080 4.3 / R3)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from credentials.pairing_store import (
    PairingStoreError,
    PairingVerdict,
    approve_pairing,
    check_pairing,
    load_pairing_store,
    record_first_use,
    require_approved_pairing,
)


def _prepare_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)


class TestPairingAbsent:
    def test_no_pairing_refuses_resolution(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_file(pairing)
        result = check_pairing("github-work", "proj-1", "https://github.com/owner/repo.git", path=pairing, skip_integrity=True)
        assert result.verdict is PairingVerdict.ABSENT
        assert result.code == "pairing-absent"
        with pytest.raises(PairingStoreError) as exc:
            require_approved_pairing(
                "github-work",
                "proj-1",
                "https://github.com/owner/repo.git",
                path=pairing,
                skip_integrity=True,
            )
        assert exc.value.code == "pairing-absent"


class TestPairingApproved:
    def test_one_approved_pairing_allows_resolution(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_file(pairing)
        record_first_use(
            "github-work",
            "proj-1",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        approve_pairing(
            "github-work",
            "proj-1",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        result = check_pairing(
            "github-work",
            "proj-1",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        assert result.verdict is PairingVerdict.ALLOWED
        record = require_approved_pairing(
            "github-work",
            "proj-1",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        assert record.status == "approved"


class TestManyPairings:
    def test_many_pairings_remain_independent(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_file(pairing)
        record_first_use("github-work", "proj-1", "https://github.com/work/repo.git", path=pairing, skip_integrity=True)
        record_first_use(
            "github-personal",
            "proj-2",
            "https://github.com/me/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        approve_pairing("github-work", "proj-1", "https://github.com/work/repo.git", path=pairing, skip_integrity=True)
        records = load_pairing_store(path=pairing, skip_integrity=True)
        assert set(records) == {"github-work", "github-personal"}
        assert check_pairing("github-work", "proj-1", "https://github.com/work/repo.git", path=pairing, skip_integrity=True).verdict is PairingVerdict.ALLOWED
        assert check_pairing("github-personal", "proj-2", "https://github.com/me/repo.git", path=pairing, skip_integrity=True).verdict is PairingVerdict.UNAPPROVED


class TestPairingPending:
    def test_pending_pairing_refuses_without_re_prompt(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_file(pairing)
        record_first_use("github-work", "proj-1", "https://github.com/owner/repo.git", path=pairing, skip_integrity=True)
        result = check_pairing(
            "github-work",
            "proj-1",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        assert result.verdict is PairingVerdict.UNAPPROVED
        assert result.code == "pairing-unapproved"
        with pytest.raises(PairingStoreError) as exc:
            require_approved_pairing(
                "github-work",
                "proj-1",
                "https://github.com/owner/repo.git",
                path=pairing,
                skip_integrity=True,
            )
        assert exc.value.code == "pairing-unapproved"


class TestPairingMismatch:
    def test_approved_pairing_mismatch_refuses_permanently(self, tmp_path: Path) -> None:
        pairing = tmp_path / "credential-pairings.json"
        _prepare_file(pairing)
        record_first_use("github-work", "proj-1", "https://github.com/owner/repo.git", path=pairing, skip_integrity=True)
        approve_pairing(
            "github-work",
            "proj-1",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        result = check_pairing(
            "github-work",
            "proj-2",
            "https://github.com/owner/repo.git",
            path=pairing,
            skip_integrity=True,
        )
        assert result.verdict is PairingVerdict.MISMATCH
        assert result.code == "pairing-mismatch"
        assert "re-prompt" in result.hint
        with pytest.raises(PairingStoreError) as exc:
            require_approved_pairing(
                "github-work",
                "proj-2",
                "https://github.com/owner/other.git",
                path=pairing,
                skip_integrity=True,
            )
        assert exc.value.code == "pairing-mismatch"
