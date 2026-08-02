"""CI selector fallback must skip machine-local pairing (PRD 080 / host smoke)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from credentials.environment_backend import register_environment_backend
from credentials.model import CredentialRef, ResolutionState
from credentials.resolver import RepositoryContext, clear_backend_adapters, resolve_lookup


_TEST_VALUE = "gh_fixture_token"
_REMOTE = "https://github.com/owner/repo.git"


def _environment_entry(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "backend": "environment",
        "provider": "github",
        "hostname": "github.com",
        "account": "ci",
        "tokenEnv": "GITHUB_TOKEN",
        "allowedRepos": ["owner/repo"],
        "allowedProjectIds": ["proj-1", "unpaired"],
        "allowedEndpoints": ["https://api.github.com"],
    }
    payload.update(overrides)
    return payload


def _write_ci_selector(root: Path, entries: dict[str, dict[str, object]]) -> None:
    path = root / ".sw" / "credential-ci-selector.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")


def _context() -> RepositoryContext:
    return RepositoryContext(
        remote=_REMOTE,
        repo_slug="owner/repo",
        project_id="proj-1",
        destination_endpoint="https://api.github.com",
    )


@pytest.fixture(autouse=True)
def _register_environment_backend() -> None:
    clear_backend_adapters()
    register_environment_backend()
    yield
    clear_backend_adapters()


def test_ci_selector_resolves_without_machine_pairing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Absent machine selector + CI declaration must not require TOFU pairing."""
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    _write_ci_selector(root, {"github-work": _environment_entry()})
    monkeypatch.setenv("GITHUB_TOKEN", _TEST_VALUE)
    monkeypatch.chdir(root)

    # Explicit absent machine-local paths (skip_integrity so integrity probe is N/A).
    result = resolve_lookup(
        CredentialRef("github-work"),
        provider="github",
        purpose="host",
        context=_context(),
        selector_path=tmp_path / "absent-selector.json",
        pairing_path=tmp_path / "absent-pairings.json",
        skip_integrity=True,
    )

    assert result.failure_code is None
    assert result.resolution.state is ResolutionState.RESOLVED
    assert result.backend == "environment"
