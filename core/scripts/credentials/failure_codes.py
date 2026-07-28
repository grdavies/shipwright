"""Stable credential resolver failure codes (PRD 080 phase 5 / R3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

MISSING_SELECTOR: Final[str] = "resolver-selector-absent"
UNKNOWN_REF: Final[str] = "resolver-unknown-ref"
UNAVAILABLE_BACKEND: Final[str] = "resolver-unavailable-backend"
MISSING_KEYSTORE_ITEM: Final[str] = "resolver-missing-keystore-item"
MISSING_CI_DECLARATION: Final[str] = "resolver-missing-ci-declaration"
PRINCIPAL_MISMATCH: Final[str] = "resolver-principal-mismatch"
OUT_OF_SCOPE_REPO: Final[str] = "resolver-out-of-scope-repo"
OUT_OF_SCOPE_PROJECT: Final[str] = "resolver-out-of-scope-project"
OUT_OF_SCOPE_ENDPOINT: Final[str] = "resolver-out-of-scope-endpoint"
UNAPPROVED_PAIRING: Final[str] = "resolver-unapproved-pairing"
PAIRING_MISMATCH: Final[str] = "resolver-pairing-mismatch"
INSUFFICIENT_ACCESS: Final[str] = "resolver-insufficient-access"
INSUFFICIENT_SCOPE: Final[str] = "resolver-insufficient-scope"
LOOKUP_TIMEOUT: Final[str] = "resolver-lookup-timeout"
MISSING_CONTEXT: Final[str] = "resolver-missing-context"
PROVIDER_MISMATCH: Final[str] = "resolver-provider-mismatch"
EMPTY_REFERENCE: Final[str] = "resolver-empty-reference"

ALL_FAILURE_CODES: Final[tuple[str, ...]] = (
    MISSING_SELECTOR,
    UNKNOWN_REF,
    UNAVAILABLE_BACKEND,
    MISSING_KEYSTORE_ITEM,
    MISSING_CI_DECLARATION,
    PRINCIPAL_MISMATCH,
    OUT_OF_SCOPE_REPO,
    OUT_OF_SCOPE_PROJECT,
    OUT_OF_SCOPE_ENDPOINT,
    UNAPPROVED_PAIRING,
    PAIRING_MISMATCH,
    INSUFFICIENT_ACCESS,
    INSUFFICIENT_SCOPE,
    LOOKUP_TIMEOUT,
    MISSING_CONTEXT,
    PROVIDER_MISMATCH,
    EMPTY_REFERENCE,
)

LEGITIMATE_HALT_CODES: Final[frozenset[str]] = frozenset({LOOKUP_TIMEOUT})


@dataclass(frozen=True, slots=True)
class FailureDetail:
    code: str
    hint: str


_FAILURE_HINTS: dict[str, str] = {
    MISSING_SELECTOR: "create the machine-local selector file under your trusted config directory",
    UNKNOWN_REF: "declare the credential reference in the selector file",
    UNAVAILABLE_BACKEND: "choose an available backend for this platform or install the required host CLI",
    MISSING_KEYSTORE_ITEM: "store the credential item in the platform keystore for this reference",
    MISSING_CI_DECLARATION: "declare the env backend in repository CI configuration or the selector file",
    PRINCIPAL_MISMATCH: "select a credential reference whose principal matches the requested provider",
    OUT_OF_SCOPE_REPO: "extend allowedRepos for this reference or use a credential scoped to the repository",
    OUT_OF_SCOPE_PROJECT: "extend allowedProjectIds for this reference or use a credential scoped to the project",
    OUT_OF_SCOPE_ENDPOINT: "extend allowedEndpoints for this reference or target an in-scope destination",
    UNAPPROVED_PAIRING: "approve the recorded first-use pairing before credential resolution",
    PAIRING_MISMATCH: "recorded pairing does not match; refusal is permanent without re-prompt",
    INSUFFICIENT_ACCESS: "grant the credential access required for the requested operation",
    INSUFFICIENT_SCOPE: "extend selector scope or choose a reference with sufficient scope",
    LOOKUP_TIMEOUT: "retry after resolving the interactive backend prompt or choose a non-interactive backend",
    MISSING_CONTEXT: "supply repository context, provider, and purpose for every lookup",
    PROVIDER_MISMATCH: "choose a selector entry whose provider matches the requested host",
    EMPTY_REFERENCE: "supply a non-empty credential reference",
}


def failure_detail(code: str, *, hint: str | None = None) -> FailureDetail:
    return FailureDetail(code=code, hint=hint or _FAILURE_HINTS.get(code, "credential resolution refused"))


def is_legitimate_halt(code: str | None) -> bool:
    return bool(code and code in LEGITIMATE_HALT_CODES)
