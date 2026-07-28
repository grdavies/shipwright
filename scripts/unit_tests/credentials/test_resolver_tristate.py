"""Tri-state branching tests for the credential resolver (PRD 080 5.4 / R3)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from credentials import failure_codes as fc
from credentials.model import CredentialRef, Principal, ResolutionState, Secret
from credentials.pairing_store import approve_pairing, record_first_use
from credentials.resolver import (
    BackendResolveResult,
    RepositoryContext,
    clear_backend_adapters,
    register_backend_adapter,
    resolve,
    resolve_lookup,
)
from credentials.selector_store import SelectorEntry


_TEST_VALUE = "unit-test-credential-value-abcdef"


@dataclass(frozen=True, slots=True)
class _StubBackend:
    backend_name: str
    result: BackendResolveResult
    delay_seconds: float = 0.0

    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = (entry, purpose, context)
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return BackendResolveResult(
            state=self.result.state,
            token=self.result.token,
            principal=self.result.principal,
            failure_code=self.result.failure_code,
            backend=self.backend_name,
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


def _write_selector(path: Path, entries: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
    os.chmod(path, 0o600)


def _write_pairing(path: Path, ref: str, project_id: str, remote: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    record_first_use(ref, project_id, remote, path=path, skip_integrity=True)
    approve_pairing(ref, project_id, remote, path=path, skip_integrity=True)


def _context(
    *,
    remote: str = "https://github.com/owner/repo.git",
    repo_slug: str = "owner/repo",
    project_id: str = "proj-1",
    destination_endpoint: str = "https://api.github.com/user",
) -> RepositoryContext:
    return RepositoryContext(
        remote=remote,
        repo_slug=repo_slug,
        project_id=project_id,
        destination_endpoint=destination_endpoint,
    )


@pytest.fixture(autouse=True)
def _reset_backend_adapters() -> None:
    clear_backend_adapters()
    yield
    clear_backend_adapters()


class TestTriStateMatrix:
    @pytest.mark.parametrize(
        ("purpose", "expected_state", "register_backend"),
        [
            ("public", ResolutionState.EXPLICITLY_NO_AUTH, False),
            ("no-auth", ResolutionState.EXPLICITLY_NO_AUTH, False),
            ("api", ResolutionState.RESOLVED, True),
            ("git", ResolutionState.RESOLVED, True),
        ],
    )
    def test_resolution_matrix_by_purpose(
        self,
        tmp_path: Path,
        purpose: str,
        expected_state: ResolutionState,
        register_backend: bool,
    ) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        if register_backend:
            register_backend_adapter(
                "github_cli",
                _StubBackend(
                    "github_cli",
                    BackendResolveResult(
                        state=ResolutionState.RESOLVED,
                        token=Secret(_TEST_VALUE),
                        principal=Principal(profile="work", account="work"),
                    ),
                ),
            )

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose=purpose,
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.resolution.state is expected_state
        if expected_state is ResolutionState.RESOLVED:
            assert result.backend == "github_cli"
            assert result.principal == Principal(profile="work", account="work")
            assert result.resolution.token is not None
            assert result.resolution.token.token.value == _TEST_VALUE
        result.resolution.ensure_no_empty_token_coercion()

    def test_many_references_remain_independent(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(
            selector,
            {
                "github-work": _valid_entry(account="work"),
                "github-personal": _valid_entry(
                    account="personal",
                    allowedRepos=["me/repo"],
                    allowedProjectIds=["proj-2"],
                ),
            },
        )
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")
        _write_pairing(pairing, "github-personal", "proj-2", "https://github.com/me/repo.git")

        register_backend_adapter(
            "github_cli",
            _StubBackend(
                "github_cli",
                BackendResolveResult(
                    state=ResolutionState.RESOLVED,
                    token=Secret(_TEST_VALUE),
                    principal=Principal(profile="work", account="work"),
                ),
            ),
        )

        work = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )
        personal = resolve_lookup(
            CredentialRef("github-personal"),
            provider="github",
            purpose="api",
            context=_context(
                remote="https://github.com/me/repo.git",
                repo_slug="me/repo",
                project_id="proj-2",
            ),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert work.resolution.state is ResolutionState.RESOLVED
        assert personal.resolution.state is ResolutionState.RESOLVED


class TestUnresolvedDoesNotCollapseToNoAuth:
    def test_unresolved_backend_does_not_imply_unauthenticated_success(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
        )

        assert result.resolution.state is ResolutionState.UNRESOLVED
        assert not result.resolution.is_explicitly_unauthenticated
        assert result.failure_code == fc.UNAVAILABLE_BACKEND
        result.resolution.ensure_no_empty_token_coercion()

    def test_empty_reference_stays_unresolved(self) -> None:
        outcome = resolve(CredentialRef(""))
        assert outcome.state is ResolutionState.UNRESOLVED
        assert outcome.reason == fc.EMPTY_REFERENCE
        with pytest.raises(ValueError, match="empty reference"):
            outcome.ensure_no_empty_token_coercion()

    def test_missing_context_stays_unresolved(self) -> None:
        outcome = resolve(CredentialRef("github-work"))
        assert outcome.state is ResolutionState.UNRESOLVED
        assert outcome.reason == fc.MISSING_CONTEXT
        outcome.ensure_no_empty_token_coercion()
