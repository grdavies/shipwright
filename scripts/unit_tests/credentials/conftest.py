"""Hermetic fixtures for credential unit tests (PRD 084 R7)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hermetic_fixture import TOKEN_ENV_VARS, apply_hermetic_recipe

__all__ = ("apply_hermetic_recipe", "HERMETIC_RECIPE_UNSET", "TOKEN_ENV_VARS")

HERMETIC_RECIPE_UNSET = TOKEN_ENV_VARS


@pytest.fixture(autouse=True)
def _hermetic_credential_test_context(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Isolate ambient tokens and machine-local selector leakage."""
    for name in TOKEN_ENV_VARS:
        monkeypatch.delenv(name, raising=False)

    hermetic_root = tmp_path / "hermetic-env"
    home = hermetic_root / "home"
    xdg = home / ".config"
    apply_hermetic_recipe({}, home=home, xdg_config_home=xdg)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))


@pytest.fixture
def hermetic_recipe_paths(tmp_path: Path) -> tuple[Path, Path]:
    """Expose the pinned HOME/XDG paths for probe tests."""
    hermetic_root = tmp_path / "hermetic-env"
    return hermetic_root / "home", hermetic_root / "home" / ".config"
