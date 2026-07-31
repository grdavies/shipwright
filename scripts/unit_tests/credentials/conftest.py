"""Hermetic fixtures for credential unit tests (PRD 083 R5)."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

_TOKEN_ENV_VARS = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "SW_PLANNING_ISSUES_TOKEN",
)


@pytest.fixture(autouse=True)
def _hermetic_credential_test_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate ambient tokens and machine-local selector leakage."""
    for name in _TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    isolated = Path.home() / ".cache" / "shipwright-hermetic-tests" / uuid.uuid4().hex
    isolated.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(isolated))
