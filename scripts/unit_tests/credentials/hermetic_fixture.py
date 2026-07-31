"""Shared hermetic-environment helpers for credential unit tests (PRD 084 R7)."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

TOKEN_ENV_VARS = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "SW_PLANNING_ISSUES_TOKEN",
)

# Manual operator recipe mirrored by the autouse conftest fixture.
HERMETIC_RECIPE_UNSET = TOKEN_ENV_VARS


def apply_hermetic_recipe(
    base: Mapping[str, str],
    *,
    home: Path,
    xdg_config_home: Path,
) -> dict[str, str]:
    """Return env with tokens cleared and HOME/XDG_CONFIG_HOME pinned."""
    env = dict(base)
    for name in TOKEN_ENV_VARS:
        env.pop(name, None)
    home.mkdir(parents=True, exist_ok=True)
    xdg_config_home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(xdg_config_home)
    return env
