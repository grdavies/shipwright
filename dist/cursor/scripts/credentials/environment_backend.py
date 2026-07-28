"""Explicit-only environment credential backend (PRD 080 phase 10 / R6)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from credentials import failure_codes as fc
from credentials.ci_declaration import (
    is_environment_backend_declared,
    resolve_presence_env_name,
)
from credentials.model import Principal, ResolutionState, Secret
from credentials.resolver import BackendResolveResult, RepositoryContext, register_backend_adapter
from credentials.selector_store import SelectorEntry

ENVIRONMENT_BACKEND_NAME: Final[str] = "environment"


@dataclass(frozen=True, slots=True)
class EnforceabilityStatement:
    """Published statement describing how environment-backend explicitness is enforced."""

    mechanism: str
    presence_env_from_host_token_env: bool
    requires_explicit_declaration: bool
    prohibits_implicit_workstation_default: bool


ENVIRONMENT_ENFORCEABILITY: Final[EnforceabilityStatement] = EnforceabilityStatement(
    mechanism="read only the host token env var after an explicit selector or CI declaration",
    presence_env_from_host_token_env=True,
    requires_explicit_declaration=True,
    prohibits_implicit_workstation_default=True,
)


def enforceability_statement() -> EnforceabilityStatement:
    return ENVIRONMENT_ENFORCEABILITY


def read_declared_env_secret(
    entry: SelectorEntry,
    *,
    root: Path | str,
    environ: Mapping[str, str] | None = None,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> str | None:
    """Read the declared env-backend secret, or None when undeclared or absent."""
    if entry.backend != ENVIRONMENT_BACKEND_NAME:
        return None
    if not is_environment_backend_declared(
        entry.ref,
        root=root,
        selector_path=selector_path,
        xdg_base=xdg_base,
    ):
        return None
    env_name = resolve_presence_env_name(entry, root=root)
    source = environ if environ is not None else os.environ
    value = source.get(env_name, "").strip()
    return value or None


class EnvironmentBackendAdapter:
    """Resolve credentials from an explicitly declared process-environment variable."""

    def __init__(
        self,
        *,
        repository_root: Path | str | None = None,
        selector_path: Path | None = None,
        xdg_base: Path | None = None,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._repository_root = (
            Path(repository_root).expanduser().resolve()
            if repository_root is not None
            else Path.cwd().resolve()
        )
        self._selector_path = selector_path
        self._xdg_base = xdg_base
        self._environ = environ

    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = (purpose, context)
        if entry.backend != ENVIRONMENT_BACKEND_NAME:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.UNAVAILABLE_BACKEND,
                backend=entry.backend,
            )

        if not is_environment_backend_declared(
            entry.ref,
            root=self._repository_root,
            selector_path=self._selector_path,
            xdg_base=self._xdg_base,
        ):
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.MISSING_CI_DECLARATION,
                backend=entry.backend,
            )

        token_value = read_declared_env_secret(
            entry,
            root=self._repository_root,
            environ=self._environ,
            selector_path=self._selector_path,
            xdg_base=self._xdg_base,
        )
        if token_value is None:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.INSUFFICIENT_ACCESS,
                backend=entry.backend,
            )

        principal = Principal(
            profile=entry.account or entry.ref,
            account=entry.account,
        )
        resolved_secret = Secret(token_value)
        return BackendResolveResult(
            state=ResolutionState.RESOLVED,
            token=resolved_secret,
            principal=principal,
            backend=entry.backend,
        )


def register_environment_backend(adapter: EnvironmentBackendAdapter | None = None) -> None:
    register_backend_adapter(ENVIRONMENT_BACKEND_NAME, adapter or EnvironmentBackendAdapter())


register_environment_backend()
