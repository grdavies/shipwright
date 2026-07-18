"""Adapter registration checklist validation against catalog rows (PRD 071 R5)."""

from __future__ import annotations

from typing import Any

from memory_provider_catalog import CAPABILITY_FLAGS, INTERCHANGE_FORMATS, load_catalog

REQUIRED_ROW_FIELDS = (
    "adapterDoc",
    "rulesScript",
    "capabilities",
    "hookTransport",
    "interchange",
    "sourceOfTruthClass",
    "credentials",
)
REQUIRED_HOOK_TRANSPORT_FIELDS = ("agentSession", "ruleFetch", "notes")
REQUIRED_CREDENTIAL_FIELDS = ("location", "notes")
CHECKLIST_MARKERS = (
    "dual-transport",
    "category map",
    "r41",
    "degrade-open",
    "interchange",
    "credential",
    "secret-store-only",
)


class ChecklistError(Exception):
    """Raised when a catalog row fails the adapter registration checklist."""

    def __init__(self, message: str, *, provider_id: str) -> None:
        super().__init__(message)
        self.provider_id = provider_id


def _require_mapping(value: Any, label: str, *, provider_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ChecklistError(f"{label} must be an object", provider_id=provider_id)
    return value


def validate_provider_checklist(provider_id: str, entry: dict[str, Any]) -> None:
    row = _require_mapping(entry, "catalog row", provider_id=provider_id)
    for field in REQUIRED_ROW_FIELDS:
        if field not in row:
            raise ChecklistError(f"missing checklist field: {field}", provider_id=provider_id)

    capabilities = _require_mapping(row["capabilities"], "capabilities", provider_id=provider_id)
    for flag in CAPABILITY_FLAGS:
        if flag not in capabilities:
            raise ChecklistError(f"missing capability flag: {flag}", provider_id=provider_id)

    hook_transport = _require_mapping(row["hookTransport"], "hookTransport", provider_id=provider_id)
    for field in REQUIRED_HOOK_TRANSPORT_FIELDS:
        if field not in hook_transport or not str(hook_transport.get(field) or "").strip():
            raise ChecklistError(f"missing hookTransport field: {field}", provider_id=provider_id)

    interchange = _require_mapping(row["interchange"], "interchange", provider_id=provider_id)
    for fmt in INTERCHANGE_FORMATS:
        if fmt not in interchange:
            raise ChecklistError(f"missing interchange format: {fmt}", provider_id=provider_id)

    credentials = _require_mapping(row["credentials"], "credentials", provider_id=provider_id)
    for field in REQUIRED_CREDENTIAL_FIELDS:
        if field not in credentials or not str(credentials.get(field) or "").strip():
            raise ChecklistError(f"missing credentials field: {field}", provider_id=provider_id)

    location = str(credentials.get("location") or "").strip().lower()
    notes = str(credentials.get("notes") or "").strip().lower()
    if location not in {"none", "env-only", "secret-store"}:
        raise ChecklistError(
            f"credentials.location must be none|env-only|secret-store: {location!r}",
            provider_id=provider_id,
        )
    if location != "none" and "secret" not in notes and "environment" not in notes:
        raise ChecklistError(
            "credentials.notes must document secret-store/env-only handling",
            provider_id=provider_id,
        )


def validate_seeded_catalog_checklist(root: Any) -> list[str]:
    from pathlib import Path

    catalog = load_catalog(Path(root))
    providers = catalog.get("providers")
    if not isinstance(providers, dict):
        raise ChecklistError("catalog providers missing", provider_id="*")
    for provider_id, entry in providers.items():
        if not isinstance(entry, dict):
            raise ChecklistError("provider row must be an object", provider_id=str(provider_id))
        validate_provider_checklist(str(provider_id), entry)
    return sorted(str(key) for key in providers)


def capabilities_doc_contains_checklist(text: str) -> bool:
    lowered = text.lower()
    return all(marker in lowered for marker in CHECKLIST_MARKERS)
