"""Backend entry-point registry — import-safe, no secret-bearing side effects."""

from __future__ import annotations

import importlib
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


def register_function_name(backend: str) -> str:
    return f"register_{backend}_backend"


def load_backend(backend: str) -> Callable[[], None]:
    """Return an idempotent loader that imports the backend module and registers its adapter.

    Import alone is not sufficient: `keystore_backend` registers only on explicit call, so the
    loader invokes the module's `register_<backend>_backend` entry point when present.
    """
    module_name = backend_module_name(backend)
    entry_point = register_function_name(backend)

    def _load() -> None:
        module = importlib.import_module(module_name)
        register = getattr(module, entry_point, None)
        if callable(register):
            register()

    return _load
