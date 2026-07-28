"""Keystore backend tests at the ctypes boundary (PRD 080 6.3 / R3)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from credentials import failure_codes as fc
from credentials.keystore_backend import (
    KeystoreBackendAdapter,
    KeystoreServiceError,
    keystore_account_name,
    keystore_service_name,
    read_keystore_secret,
    set_keystore_bindings,
)
from credentials.model import ResolutionState
from credentials.resolver import RepositoryContext
from credentials.selector_store import SelectorEntry


_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


@dataclass(frozen=True, slots=True)
class _StubBindings:
    payload: bytes | None = None
    error: KeystoreServiceError | None = None

    def read_generic_secret(self, *, service: str, account: str) -> bytes | None:
        _ = (service, account)
        if self.error is not None:
            raise self.error
        return self.payload


def _entry(ref: str = "github-work", **overrides: object) -> SelectorEntry:
    payload = {
        "ref": ref,
        "backend": "keystore",
        "provider": "github",
        "hostname": "github.com",
        "account": "work",
        "allowed_repos": ("owner/repo",),
        "allowed_project_ids": ("proj-1",),
        "allowed_endpoints": ("https://api.github.com",),
    }
    payload.update(overrides)
    return SelectorEntry(**payload)


@pytest.fixture(autouse=True)
def _reset_bindings() -> None:
    set_keystore_bindings(None)
    yield
    set_keystore_bindings(None)


class TestKeystoreNaming:
    def test_service_name_uses_reference(self) -> None:
        assert keystore_service_name("github-work") == "shipwright.credential.github-work"

    def test_account_prefers_selector_account(self) -> None:
        entry = _entry(account="work", hostname="github.com")
        assert keystore_account_name(entry) == "work"


class TestKeystoreBackendAdapter:
    def test_missing_item_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(payload=None))
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(
            _entry(),
            purpose="api",
            context=RepositoryContext(
                remote="https://github.com/owner/repo.git",
                repo_slug="owner/repo",
                project_id="proj-1",
                destination_endpoint="https://api.github.com/user",
            ),
        )
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.MISSING_KEYSTORE_ITEM

    def test_one_present_item_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(payload=_TEST_VALUE.encode("utf-8")))
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.RESOLVED
        assert result.token is not None
        assert result.token.value == _TEST_VALUE
        assert result.principal is not None
        assert result.principal.account == "work"

    def test_many_refs_use_distinct_service_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        seen: list[tuple[str, str]] = []

        class _RecordingBindings:
            def read_generic_secret(self, *, service: str, account: str) -> bytes | None:
                seen.append((service, account))
                return _TEST_VALUE.encode("utf-8")

        set_keystore_bindings(_RecordingBindings())
        adapter = KeystoreBackendAdapter()
        for ref in ("ref-a", "ref-b", "ref-c"):
            result = adapter.resolve(_entry(ref=ref), purpose="api", context=_context())
            assert result.state is ResolutionState.RESOLVED
        assert seen == [
            (keystore_service_name("ref-a"), "work"),
            (keystore_service_name("ref-b"), "work"),
            (keystore_service_name("ref-c"), "work"),
        ]

    def test_unavailable_keystore_service_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(error=KeystoreServiceError(fc.UNAVAILABLE_BACKEND)))
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == fc.UNAVAILABLE_BACKEND


class TestReadKeystoreSecret:
    def test_read_returns_decoded_secret(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "credentials.keystore_backend.validate_backend_for_platform",
            lambda _backend: None,
        )
        set_keystore_bindings(_StubBindings(payload=b"token-value"))
        assert read_keystore_secret(_entry()) == "token-value"


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )
