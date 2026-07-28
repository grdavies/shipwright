"""Backend entry-point registry — import-safe, no secret-bearing side effects."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

BACKEND_NAMES: Final[tuple[str, ...]] = (
    "environment",
    "github_cli",
    "git_credential",
    "keystore",
)

_BACKEND_MODULES: Final[dict[str, str]] = {
    "environment": "credentials.environment_backend",
    "github_cli": "credentials.github_cli_backend",
    "git_credential": "credentials.git_credential_backend",
    "keystore": "credentials.keystore_backend",
}


def backend_module_name(backend: str) -> str:
    try:
        return _BACKEND_MODULES[backend]
    except KeyError as exc:
        raise ValueError(f"unknown credential backend: {backend}") from exc


def list_backends() -> tuple[str, ...]:
    return BACKEND_NAMES


def load_backend(backend: str) -> Callable[[], None]:
    """Return a no-op placeholder until backend modules ship in later phases."""
    _ = backend_module_name(backend)

    def _placeholder() -> None:
        return None

    return _placeholder
