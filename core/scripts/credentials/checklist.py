"""Ordered credential checklist steps shared by init guidance and doctor (PRD 324 R1)."""

from __future__ import annotations

from typing import Final

IDENTITY_SOURCE: Final[str] = "identity-source"
CREDENTIAL_REF: Final[str] = "credential-ref"
SELECTOR_ALLOWLISTS: Final[str] = "selector-allowlists"
RESOLUTION_PROBE: Final[str] = "resolution-probe"

CHECKLIST_STEP_ORDER: Final[tuple[str, ...]] = (
    IDENTITY_SOURCE,
    CREDENTIAL_REF,
    SELECTOR_ALLOWLISTS,
    RESOLUTION_PROBE,
)

CHECKLIST_STEP_LABELS: Final[dict[str, str]] = {
    IDENTITY_SOURCE: "Identity source",
    CREDENTIAL_REF: "credentialRef binding",
    SELECTOR_ALLOWLISTS: "Selector allowlists",
    RESOLUTION_PROBE: "Resolution probe",
}

CONFIGURE_CREDENTIAL_PLAN: Final[str] = "python3 scripts/sw-configure.py credential plan"
CONFIGURE_CREDENTIAL_APPLY: Final[str] = (
    "python3 scripts/sw-configure.py credential apply --confirm"
)
CONFIGURE_CREDENTIAL_MIGRATE: Final[str] = (
    "python3 scripts/sw-configure.py credential migrate --confirm"
)
CONFIGURE_CREDENTIAL_SELECTOR_ADD: Final[str] = (
    "python3 scripts/sw-configure.py credential selector-add"
)
