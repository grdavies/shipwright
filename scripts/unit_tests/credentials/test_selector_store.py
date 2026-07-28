"""Selector loader fail-closed tests (PRD 080 2.4 / R2)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from credentials.selector_store import (
    SelectorStoreError,
    default_selector_path,
    load_selector_store,
    resolve_xdg_config_home,
    validate_trusted_xdg_base,
)


def _valid_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "github_cli",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    payload.update(overrides)
    return payload


def _write_selector(path: Path, entries: dict[str, dict[str, object]] | None = None) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    document = {
        "version": 1,
        "entries": entries
        or {
            "github-work": _valid_entry(),
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    os.chmod(path, 0o600)


class TestSelectorAbsent:
    def test_missing_file_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        with pytest.raises(SelectorStoreError, match="selector-absent"):
            load_selector_store(path=selector)


class TestSelectorValid:
    def test_one_valid_entry_loads(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector)
        doc = load_selector_store(path=selector, skip_integrity=True)
        entry = doc.entries["github-work"]
        assert entry.backend == "github_cli"
        assert entry.allowed_repos == ("owner/repo",)

    def test_many_entries_remain_independent(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(
            selector,
            {
                "github-work": _valid_entry(account="work"),
                "github-personal": _valid_entry(account="personal", allowedRepos=["me/repo"]),
            },
        )
        doc = load_selector_store(path=selector, skip_integrity=True)
        assert set(doc.entries) == {"github-work", "github-personal"}
        assert doc.entries["github-personal"].allowed_repos == ("me/repo",)


class TestSelectorUnknownBackend:
    def test_unknown_backend_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        _write_selector(selector, {"github-work": _valid_entry(backend="vault")})
        with pytest.raises(SelectorStoreError) as exc:
            load_selector_store(path=selector, skip_integrity=True)
        assert exc.value.code == "selector-unknown-backend"
        assert "unknown backend" in exc.value.hint


class TestSelectorMandatoryScope:
    @pytest.mark.parametrize(
        ("field", "code"),
        [
            ("allowedRepos", "selector-missing-allowed-repos"),
            ("allowedProjectIds", "selector-missing-allowed-project-ids"),
            ("allowedEndpoints", "selector-missing-allowed-endpoints"),
        ],
    )
    def test_missing_scope_field_fails_closed(
        self,
        tmp_path: Path,
        field: str,
        code: str,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        entry = _valid_entry()
        entry.pop(field)
        _write_selector(selector, {"github-work": entry})
        with pytest.raises(SelectorStoreError) as exc:
            load_selector_store(path=selector, skip_integrity=True)
        assert exc.value.code == code
        assert field in exc.value.hint


class TestTrustedXdgBase:
    def test_untrusted_xdg_base_fails_closed(self, tmp_path: Path) -> None:
        with pytest.raises(SelectorStoreError) as exc:
            validate_trusted_xdg_base(tmp_path / "outside-home")
        assert exc.value.code == "selector-untrusted-xdg-base"

    def test_trusted_xdg_base_resolves_under_home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr("credentials.selector_store.trusted_user_root", lambda: home.resolve())
        config = home / ".config"
        resolved = resolve_xdg_config_home(config)
        assert resolved == config.resolve()
        assert default_selector_path(xdg_base=config) == config / "shipwright" / "credential-selector.json"
