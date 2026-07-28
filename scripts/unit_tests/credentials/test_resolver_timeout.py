"""Timeout and non-interactivity tests for the credential resolver (PRD 080 5.5 / R3)."""

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
    resolve_lookup,
)
from credentials.selector_store import SelectorEntry
from halt_resume import enrich_legitimate_halt


_TEST_VALUE = "sk_test_fixture_allowlisted_secret_scan_0123456789"


def _resolved_backend() -> BackendResolveResult:
    return BackendResolveResult(
        ResolutionState.RESOLVED,
        Secret(_TEST_VALUE),
        Principal(profile="work", account="work"),
        None,
        "keystore",
    )


@dataclass(frozen=True, slots=True)
class _BlockingBackend:
    backend_name: str
    delay_seconds: float

    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = (entry, purpose, context)
        time.sleep(self.delay_seconds)
        return BackendResolveResult(
            ResolutionState.RESOLVED,
            Secret(_TEST_VALUE),
            Principal(profile="work", account="work"),
            None,
            self.backend_name,
        )


def _valid_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "keystore",
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


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote="https://github.com/owner/repo.git",
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com/user",
    )


@pytest.fixture(autouse=True)
def _reset_backend_adapters() -> None:
    clear_backend_adapters()
    yield
    clear_backend_adapters()


class TestLookupTimeout:
    def test_blocking_backend_hits_hard_timeout_and_fails_closed(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")
        register_backend_adapter("keystore", _BlockingBackend("keystore", delay_seconds=0.5))

        started = time.monotonic()
        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            timeout_seconds=0.1,
        )
        elapsed = time.monotonic() - started

        assert elapsed < 0.25
        assert result.failure_code == fc.LOOKUP_TIMEOUT
        assert result.resolution.state is ResolutionState.UNRESOLVED
        assert result.legitimate_halt is True
        assert result.halt_cause == fc.LOOKUP_TIMEOUT
        assert result.resolution.token is None
        result.resolution.ensure_no_empty_token_coercion()

    def test_timeout_is_recorded_as_legitimate_conductor_halt(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry()})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")
        register_backend_adapter("keystore", _BlockingBackend("keystore", delay_seconds=0.5))

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            timeout_seconds=0.1,
        )

        payload = enrich_legitimate_halt(
            {"cause": result.halt_cause},
            tmp_path,
            None,
            halt_cause=result.halt_cause or fc.LOOKUP_TIMEOUT,
            phase_slug="resolver-precedence-scope-tri-state-timeouts-medium",
        )

        assert payload["haltResume"]["haltCause"] == fc.LOOKUP_TIMEOUT
        assert payload["haltResume"]["phaseSlug"] == "resolver-precedence-scope-tri-state-timeouts-medium"
        assert fc.is_legitimate_halt(result.failure_code)

    def test_fast_backend_completes_within_timeout(self, tmp_path: Path) -> None:
        selector = tmp_path / "credential-selector.json"
        pairing = tmp_path / "credential-pairings.json"
        _write_selector(selector, {"github-work": _valid_entry(backend="github_cli")})
        _write_pairing(pairing, "github-work", "proj-1", "https://github.com/owner/repo.git")
        register_backend_adapter(
            "github_cli",
            _BlockingBackend("github_cli", delay_seconds=0.01),
        )

        result = resolve_lookup(
            CredentialRef("github-work"),
            provider="github",
            purpose="api",
            context=_context(),
            selector_path=selector,
            pairing_path=pairing,
            skip_integrity=True,
            timeout_seconds=1.0,
        )

        assert result.resolution.state is ResolutionState.RESOLVED
        assert result.failure_code is None
        assert result.legitimate_halt is False
