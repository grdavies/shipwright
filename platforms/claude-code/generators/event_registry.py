"""Claude Code event registry derived from core/schemas/events.json (PRD 349 R2)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_EVENTS_PATH = _REPO_ROOT / "core" / "schemas" / "events.json"
_HOST = "claude-code"


class EventRegistryError(RuntimeError):
    """Fail-closed event map errors."""


@lru_cache(maxsize=1)
def _load_events_document() -> dict[str, Any]:
    if not _EVENTS_PATH.is_file():
        raise EventRegistryError(f"canonical event map missing: {_EVENTS_PATH}")
    data = json.loads(_EVENTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise EventRegistryError("events.json must contain an events array")
    return data


def registered_host_events(host: str = _HOST) -> list[str]:
    """Host event names this adapter may register (excludes unsupported)."""
    names: list[str] = []
    for entry in _load_events_document()["events"]:
        if not isinstance(entry, dict):
            continue
        unsupported = list(entry.get("unsupported_on") or [])
        if host in unsupported:
            continue
        if entry.get("unsupported_flag") is True and not (entry.get("hosts") or {}).get(host):
            continue
        hosts = entry.get("hosts") or {}
        if not isinstance(hosts, dict):
            continue
        host_name = hosts.get(host)
        if isinstance(host_name, str) and host_name.strip():
            names.append(host_name.strip())
    assert_no_context_switch_registration(names)
    return names


def unsupported_events(host: str = _HOST) -> list[dict[str, Any]]:
    """Events marked unsupported for host, each with unsupported_flag true."""
    rows: list[dict[str, Any]] = []
    for entry in _load_events_document()["events"]:
        if not isinstance(entry, dict):
            continue
        unsupported = list(entry.get("unsupported_on") or [])
        hosts = entry.get("hosts") or {}
        flagged = bool(entry.get("unsupported_flag"))
        if host in unsupported or (flagged and not hosts.get(host)):
            rows.append(
                {
                    "canonical": entry.get("canonical"),
                    "unsupported_flag": True,
                    "host": host,
                }
            )
    return rows


def assert_no_context_switch_registration(events: list[str]) -> None:
    if any(name == "ContextSwitch" for name in events):
        raise EventRegistryError("ContextSwitch must not appear in registered events")
