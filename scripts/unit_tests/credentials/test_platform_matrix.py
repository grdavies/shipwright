"""Platform matrix fail-closed tests (PRD 080 6.4 / R3)."""

from __future__ import annotations

import pytest

from credentials import failure_codes as fc
from credentials.keystore_backend import KeystoreBackendAdapter
from credentials.model import ResolutionState
from credentials.platform_matrix import (
    KEYSTORE_LINUX_REMEDIATION_CODE,
    KEYSTORE_LINUX_REMEDIATION_HINT,
    HostPlatform,
    PlatformMatrixError,
    detect_host_platform,
    keystore_supported_on_host,
    validate_backend_for_platform,
)
from credentials.resolver import RepositoryContext
from credentials.selector_store import SelectorEntry


def _entry() -> SelectorEntry:
    return SelectorEntry(
        ref="github-work",
        backend="keystore",
        provider="github",
        hostname="github.com",
        account="work",
        allowed_repos=("owner/repo",),
        allowed_project_ids=("proj-1",),
        allowed_endpoints=("https://api.github.com",),
    )


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


class TestPlatformMatrix:
    def test_selecting_keystore_on_linux_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("credentials.platform_matrix.detect_host_platform", lambda: HostPlatform.LINUX)
        monkeypatch.setattr("credentials.platform_matrix.is_running_in_container", lambda: False)
        assert not keystore_supported_on_host()
        with pytest.raises(PlatformMatrixError) as exc:
            validate_backend_for_platform("keystore")
        assert exc.value.code == KEYSTORE_LINUX_REMEDIATION_CODE
        assert "environment" in exc.value.hint
        assert "github_cli" in exc.value.hint

    def test_linux_keystore_resolution_has_no_file_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("credentials.platform_matrix.detect_host_platform", lambda: HostPlatform.LINUX)
        monkeypatch.setattr("credentials.platform_matrix.is_running_in_container", lambda: False)
        adapter = KeystoreBackendAdapter()
        result = adapter.resolve(_entry(), purpose="api", context=_context())
        assert result.state is ResolutionState.UNRESOLVED
        assert result.failure_code == KEYSTORE_LINUX_REMEDIATION_CODE
        assert result.failure_code != fc.MISSING_KEYSTORE_ITEM

    def test_container_keystore_selection_fails_closed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("credentials.platform_matrix.detect_host_platform", lambda: HostPlatform.DARWIN)
        monkeypatch.setattr("credentials.platform_matrix.is_running_in_container", lambda: True)
        with pytest.raises(PlatformMatrixError) as exc:
            validate_backend_for_platform("keystore")
        assert exc.value.code == KEYSTORE_LINUX_REMEDIATION_CODE
        assert exc.value.hint == KEYSTORE_LINUX_REMEDIATION_HINT

    def test_non_keystore_backend_is_not_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("credentials.platform_matrix.detect_host_platform", lambda: HostPlatform.LINUX)
        validate_backend_for_platform("github_cli")

    def test_detect_host_platform_maps_linux(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("credentials.platform_matrix.sys.platform", "linux")
        assert detect_host_platform() is HostPlatform.LINUX
