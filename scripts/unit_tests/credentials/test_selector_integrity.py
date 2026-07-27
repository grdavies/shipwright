"""Selector integrity tests (PRD 080 2.5 / R2)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials.selector_integrity import (
    SelectorIntegrityError,
    check_selector_integrity,
    digest_change_warnings,
    entry_content_digest,
    entry_digests,
    verify_selector_path,
)
from credentials.selector_store import SelectorStoreError, load_selector_store


def _write_selector(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "entries": {
                    "github-work": {
                        "backend": "github_cli",
                        "provider": "github",
                        "allowedRepos": ["owner/repo"],
                        "allowedProjectIds": ["proj-1"],
                        "allowedEndpoints": ["https://api.github.com"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    os.chmod(path, 0o600)


class TestSelectorIntegrityModes:
    def test_wrong_file_mode_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        os.chmod(selector, 0o644)
        with pytest.raises(SelectorIntegrityError) as exc:
            verify_selector_path(selector)
        assert exc.value.code == "selector-integrity-file-mode"

    def test_wrong_directory_mode_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "shipwright" / "credential-selector.json"
        _write_selector(selector)
        os.chmod(selector.parent, 0o755)
        with pytest.raises(SelectorIntegrityError) as exc:
            verify_selector_path(selector)
        assert exc.value.code == "selector-integrity-dir-mode"


class TestSelectorIntegrityOwnership:
    def test_non_owner_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        with pytest.raises(SelectorIntegrityError) as exc:
            verify_selector_path(selector, uid=0)
        assert exc.value.code == "selector-integrity-owner"


class TestSelectorIntegritySymlinks:
    def test_symlinked_file_fails_closed(self, tmp_path: Path) -> None:
        real = tmp_path / "real.json"
        link = tmp_path / "credential-selector.json"
        _write_selector(real)
        link.symlink_to(real)
        with pytest.raises(SelectorIntegrityError) as exc:
            verify_selector_path(link)
        assert exc.value.code == "selector-integrity-symlink"

    def test_symlinked_parent_fails_closed(self, tmp_path: Path) -> None:
        real_dir = tmp_path / "real"
        real_dir.mkdir()
        os.chmod(real_dir, 0o700)
        link_dir = tmp_path / "shipwright"
        link_dir.symlink_to(real_dir)
        selector = link_dir / "credential-selector.json"
        _write_selector(selector)
        with pytest.raises(SelectorIntegrityError) as exc:
            verify_selector_path(selector)
        assert exc.value.code == "selector-integrity-symlink"


class TestDigestWarnings:
    def test_digest_change_emits_warning(self) -> None:
        previous_entry = {
            "backend": "github_cli",
            "provider": "github",
            "allowedRepos": ["owner/repo"],
            "allowedProjectIds": ["proj-1"],
            "allowedEndpoints": ["https://api.github.com"],
        }
        first = {"github-work": entry_content_digest(previous_entry)}
        second = entry_digests(
            {
                "version": 1,
                "entries": {
                    "github-work": {
                        **previous_entry,
                        "allowedRepos": ["owner/other"],
                    }
                },
            }
        )
        warnings = digest_change_warnings(second, first)
        assert warnings == ["selector-digest-changed:github-work"]

    def test_load_surfaces_digest_warning(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        previous = entry_digests(json.loads(selector.read_text(encoding="utf-8")))
        selector.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": {
                        "github-work": {
                            "backend": "github_cli",
                            "provider": "github",
                            "allowedRepos": ["owner/other"],
                            "allowedProjectIds": ["proj-1"],
                            "allowedEndpoints": ["https://api.github.com"],
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        os.chmod(selector, 0o600)
        os.chmod(selector.parent, 0o700)
        doc = load_selector_store(path=selector, previous_digests=previous)
        assert doc.integrity.warnings == ("selector-digest-changed:github-work",)


class TestUntrustedXdgBase:
    def test_untrusted_xdg_base_fails_closed_on_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("credentials.selector_store.trusted_user_root", lambda: home.resolve())
        outside = tmp_path / "outside"
        outside.mkdir()
        selector = outside / "shipwright" / "credential-selector.json"
        _write_selector(selector)
        with pytest.raises(SelectorStoreError) as exc:
            load_selector_store(xdg_base=outside)
        assert exc.value.code == "selector-untrusted-xdg-base"

    def test_integrity_report_ok_for_valid_file(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        report = check_selector_integrity(selector)
        assert report.verdict == "ok"
        assert report.warnings == ()
