"""Sanctioned credential broker surface — model, resolver, and backend entry points."""

from __future__ import annotations

from credentials.backends import BACKEND_NAMES, backend_module_name, list_backends, load_backend
from credentials.model import (
    CredentialRef,
    Principal,
    Resolution,
    ResolutionState,
    ResolvedToken,
    Secret,
    redact_secret_value,
)
from credentials.resolver import RepositoryContext, resolve, resolve_lookup

__all__ = [
    "BACKEND_NAMES",
    "CredentialRef",
    "Principal",
    "Resolution",
    "ResolutionState",
    "ResolvedToken",
    "Secret",
    "backend_module_name",
    "list_backends",
    "load_backend",
    "redact_secret_value",
    "RepositoryContext",
    "resolve",
    "resolve_lookup",
]
