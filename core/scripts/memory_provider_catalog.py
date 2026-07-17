#!/usr/bin/env python3
"""Load and validate the memory provider capability catalog (PRD 071 R2)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_REL = Path(".sw/memory-provider-catalog.json")
CAPABILITY_FLAGS = frozenset(
    {
        "typedMemories",
        "filePathSearch",
        "categoryFilter",
        "recencyControl",
        "rulesAtStartup",
        "tasks",
        "export",
        "import",
        "softDelete",
        "semanticSearch",
    }
)
INTERCHANGE_FORMATS = frozenset({"jsonl", "okf"})
INTERCHANGE_MODES = frozenset({"native", "synthesized", "unsupported"})
HOOK_AGENT_SESSION = frozenset({"mcp", "filesystem", "rest"})
HOOK_RULE_FETCH = frozenset({"out-of-band-script", "inline-filesystem", "none"})
SOURCE_OF_TRUTH_CLASSES = frozenset({"memory-authoritative", "repo-authoritative"})
SEEDED_PROVIDER_IDS = frozenset({"recallium", "in-repo"})


class CatalogError(Exception):
    """Raised when the catalog is missing, malformed, or incomplete."""

    def __init__(self, message: str, *, cause: str) -> None:
        super().__init__(message)
        self.cause = cause


def resolve_catalog_path(root: Path) -> Path:
    return (root / CATALOG_REL).resolve()


def load_catalog_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"catalog missing: {path}", cause="missing") from exc


def parse_catalog_json(text: str, *, path: Path | None = None) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        label = str(path) if path is not None else "catalog"
        raise CatalogError(f"catalog malformed JSON at {label}: {exc}", cause="malformed") from exc


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CatalogError(f"{label} must be an object", cause="partial")
    return value


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise CatalogError(f"{label} must be a boolean", cause="partial")
    return value


def _require_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CatalogError(f"{label} must be a non-empty string", cause="partial")
    return value.strip()


def validate_provider_entry(provider_id: str, entry: Any) -> dict[str, Any]:
    label = f"providers.{provider_id}"
    row = _require_mapping(entry, label)

    capabilities = _require_mapping(row.get("capabilities"), f"{label}.capabilities")
    for flag in CAPABILITY_FLAGS:
        _require_bool(capabilities.get(flag), f"{label}.capabilities.{flag}")

    hook_transport = _require_mapping(row.get("hookTransport"), f"{label}.hookTransport")
    agent_session = _require_str(hook_transport.get("agentSession"), f"{label}.hookTransport.agentSession")
    rule_fetch = _require_str(hook_transport.get("ruleFetch"), f"{label}.hookTransport.ruleFetch")
    if agent_session not in HOOK_AGENT_SESSION:
        raise CatalogError(
            f"{label}.hookTransport.agentSession invalid: {agent_session!r}",
            cause="partial",
        )
    if rule_fetch not in HOOK_RULE_FETCH:
        raise CatalogError(
            f"{label}.hookTransport.ruleFetch invalid: {rule_fetch!r}",
            cause="partial",
        )
    notes = hook_transport.get("notes")
    if notes is not None:
        _require_str(notes, f"{label}.hookTransport.notes")

    interchange = _require_mapping(row.get("interchange"), f"{label}.interchange")
    for fmt in INTERCHANGE_FORMATS:
        mode = _require_str(interchange.get(fmt), f"{label}.interchange.{fmt}")
        if mode not in INTERCHANGE_MODES:
            raise CatalogError(f"{label}.interchange.{fmt} invalid: {mode!r}", cause="partial")

    source_class = _require_str(row.get("sourceOfTruthClass"), f"{label}.sourceOfTruthClass")
    if source_class not in SOURCE_OF_TRUTH_CLASSES:
        raise CatalogError(
            f"{label}.sourceOfTruthClass invalid: {source_class!r}",
            cause="partial",
        )

    _require_str(row.get("adapterDoc"), f"{label}.adapterDoc")
    _require_str(row.get("rulesScript"), f"{label}.rulesScript")

    credentials = row.get("credentials")
    if credentials is not None:
        cred = _require_mapping(credentials, f"{label}.credentials")
        _require_str(cred.get("location"), f"{label}.credentials.location")

    return row


def validate_catalog(data: Any) -> dict[str, Any]:
    doc = _require_mapping(data, "catalog")
    version = doc.get("version")
    if version != 1:
        raise CatalogError(f"catalog version must be 1, got {version!r}", cause="partial")

    providers = _require_mapping(doc.get("providers"), "providers")
    if not providers:
        raise CatalogError("providers must be non-empty", cause="partial")

    validated: dict[str, Any] = {}
    for provider_id, entry in providers.items():
        if not isinstance(provider_id, str) or not provider_id.strip():
            raise CatalogError("provider ids must be non-empty strings", cause="partial")
        validated[provider_id] = validate_provider_entry(provider_id, entry)

    missing = sorted(SEEDED_PROVIDER_IDS - set(validated))
    if missing:
        raise CatalogError(
            f"catalog missing seeded providers: {', '.join(missing)}",
            cause="partial",
        )

    return {"version": 1, "description": doc.get("description"), "providers": validated}


def load_catalog(root: Path, *, validate: bool = True) -> dict[str, Any]:
    path = resolve_catalog_path(root)
    text = load_catalog_text(path)
    data = parse_catalog_json(text, path=path)
    if not validate:
        return data if isinstance(data, dict) else {}
    return validate_catalog(data)


def provider_ids(catalog: dict[str, Any]) -> frozenset[str]:
    providers = catalog.get("providers")
    if not isinstance(providers, dict):
        return frozenset()
    return frozenset(str(key) for key in providers)


def get_provider(catalog: dict[str, Any], provider_id: str) -> dict[str, Any]:
    providers = catalog.get("providers")
    if not isinstance(providers, dict):
        raise CatalogError(f"unknown provider: {provider_id}", cause="partial")
    entry = providers.get(provider_id)
    if not isinstance(entry, dict):
        raise CatalogError(f"unknown provider: {provider_id}", cause="partial")
    return entry
