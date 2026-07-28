"""Append-only credential provenance journal (PRD 080 phase 4 / R7)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from credentials.selector_integrity import (
    SELECTOR_DIR_MODE,
    SELECTOR_FILE_MODE,
    SelectorIntegrityError,
    verify_selector_path,
)
from credentials.selector_store import resolve_xdg_config_home, validate_trusted_xdg_base
from secret_patterns import DENY_PATTERNS

JOURNAL_SECRET_PATTERN_NAMES = frozenset(
    {
        "AWS_KEY",
        "GITHUB_PAT",
        "GITHUB_PAT_FINE",
        "GITHUB_OAUTH",
        "GITHUB_USER",
        "GITHUB_SERVER",
        "GITHUB_REFRESH",
        "BEARER_TOKEN",
        "JWT",
        "PEM_PRIVATE_KEY",
        "DB_URL",
        "WEBHOOK_SECRET",
        "API_SECRET",
        "API_RESTRICTED_KEY",
        "HIGH_ENTROPY_SECRET",
    }
)

JOURNAL_FILENAME = "credential-provenance.journal.jsonl"
JOURNAL_RELATIVE = Path("shipwright") / JOURNAL_FILENAME


class ProvenanceJournalError(Exception):
    """Fail-closed provenance journal error with a stable code and remediation hint."""

    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(f"{code}: {hint}")


class ProvenanceEvent(str, Enum):
    PAIRING_APPROVAL = "pairing_approval"
    SCOPE_CHANGE = "scope_change"
    ROTATION = "rotation"


@dataclass(frozen=True, slots=True)
class ProvenanceEntry:
    event: str
    recorded_at: str
    metadata: dict[str, str]


def default_journal_path(*, xdg_base: Path | None = None) -> Path:
    return resolve_xdg_config_home(xdg_base) / JOURNAL_RELATIVE


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, SELECTOR_DIR_MODE)


def _verify_journal_path(path: Path, *, skip_integrity: bool) -> None:
    if skip_integrity:
        return
    if not path.exists():
        _ensure_parent(path)
        path.touch()
        os.chmod(path, SELECTOR_FILE_MODE)
        return
    verify_selector_path(path)


def contains_secret_material(text: str) -> bool:
    for pattern in DENY_PATTERNS:
        if pattern.name not in JOURNAL_SECRET_PATTERN_NAMES:
            continue
        if pattern.pattern.search(text):
            return True
    return False


def _validate_metadata(event: ProvenanceEvent, metadata: dict[str, Any]) -> dict[str, str]:
    if not isinstance(metadata, dict):
        raise ProvenanceJournalError(
            "provenance-invalid-metadata",
            "provenance metadata must be an object",
        )
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        if not isinstance(key, str) or not key.strip():
            raise ProvenanceJournalError(
                "provenance-invalid-metadata",
                "provenance metadata keys must be non-empty strings",
            )
        if not isinstance(value, str):
            raise ProvenanceJournalError(
                "provenance-invalid-metadata",
                f"provenance metadata value for {key!r} must be a string",
            )
        normalized[key.strip()] = value.strip()
    payload = json.dumps({"event": event.value, "metadata": normalized}, sort_keys=True)
    if contains_secret_material(payload):
        raise ProvenanceJournalError(
            "provenance-secret-bearing",
            "provenance journal entries must not contain secret material",
        )
    return normalized


def _entry_from_line(line: str) -> ProvenanceEntry:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError as exc:
        raise ProvenanceJournalError(
            "provenance-invalid-json",
            "provenance journal line must be valid JSON",
        ) from exc
    if not isinstance(raw, dict):
        raise ProvenanceJournalError(
            "provenance-invalid-json",
            "provenance journal entry must be an object",
        )
    event = raw.get("event")
    recorded_at = raw.get("recordedAt")
    metadata = raw.get("metadata")
    if event not in {item.value for item in ProvenanceEvent}:
        raise ProvenanceJournalError(
            "provenance-invalid-event",
            "provenance journal event must be pairing_approval, scope_change, or rotation",
        )
    if not isinstance(recorded_at, str) or not recorded_at.strip():
        raise ProvenanceJournalError(
            "provenance-invalid-json",
            "provenance journal entry must declare recordedAt",
        )
    if not isinstance(metadata, dict):
        raise ProvenanceJournalError(
            "provenance-invalid-metadata",
            "provenance journal entry must declare metadata",
        )
    normalized = _validate_metadata(ProvenanceEvent(event), metadata)
    return ProvenanceEntry(event=event, recorded_at=recorded_at.strip(), metadata=normalized)


def load_journal(
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> list[ProvenanceEntry]:
    if xdg_base is not None:
        validate_trusted_xdg_base(xdg_base)
    journal_path = (path or default_journal_path(xdg_base=xdg_base)).expanduser()
    _verify_journal_path(journal_path, skip_integrity=skip_integrity)
    if not journal_path.exists() or journal_path.stat().st_size == 0:
        return []
    entries: list[ProvenanceEntry] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entries.append(_entry_from_line(line))
    return entries


def append_entry(
    event: ProvenanceEvent,
    metadata: dict[str, Any],
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> ProvenanceEntry:
    if xdg_base is not None:
        validate_trusted_xdg_base(xdg_base)
    journal_path = (path or default_journal_path(xdg_base=xdg_base)).expanduser()
    _verify_journal_path(journal_path, skip_integrity=skip_integrity)
    normalized = _validate_metadata(event, metadata)
    entry_doc = {
        "event": event.value,
        "recordedAt": _utc_now(),
        "metadata": normalized,
    }
    serialized = json.dumps(entry_doc, sort_keys=True, separators=(",", ":"))
    if contains_secret_material(serialized):
        raise ProvenanceJournalError(
            "provenance-secret-bearing",
            "provenance journal entries must not contain secret material",
        )
    _ensure_parent(journal_path)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(serialized + "\n")
    os.chmod(journal_path, SELECTOR_FILE_MODE)
    return ProvenanceEntry(
        event=event.value,
        recorded_at=entry_doc["recordedAt"],
        metadata=normalized,
    )
