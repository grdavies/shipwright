"""OpenCode lifecycle hook registry from core/schemas/events.json (PRD 349 R28–R30)."""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVENTS_PATH = _REPO_ROOT / "core" / "schemas" / "events.json"
_HOST = "opencode"

TOOL_PERMISSION_MODE = "explicit_user_confirmation"
POSITIONAL_ARG_START_INDEX = 1
INSTRUCTION_DISCOVERY = "adapter_resolved_path"


class HookRegistryError(RuntimeError):
    """Fail-closed OpenCode hook registry errors."""


@lru_cache(maxsize=1)
def _load_events_document() -> dict[str, Any]:
    if not _EVENTS_PATH.is_file():
        raise HookRegistryError(f"canonical event map missing: {_EVENTS_PATH}")
    data = json.loads(_EVENTS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise HookRegistryError("events.json must contain an events array")
    return data


def registered_handlers(host: str = _HOST) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for entry in _load_events_document()["events"]:
        if not isinstance(entry, dict):
            continue
        unsupported = list(entry.get("unsupported_on") or [])
        if host in unsupported:
            continue
        if entry.get("unsupported_flag") is True and not (entry.get("hosts") or {}).get(host):
            continue
        hosts = entry.get("hosts") or {}
        host_name = hosts.get(host) if isinstance(hosts, dict) else None
        if isinstance(host_name, str) and host_name.strip():
            rows.append(
                {
                    "canonical": str(entry.get("canonical") or ""),
                    "host_event": host_name.strip(),
                    "handler": "lifecycle_plugin.ts",
                }
            )
    return rows


def unsupported_events(host: str = _HOST) -> list[dict[str, Any]]:
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
                    "diagnostic": {
                        "code": "unsupported_event",
                        "message": (
                            f"event {entry.get('canonical')!r} is unsupported on {host}; "
                            "not registered"
                        ),
                    },
                }
            )
    return rows


def build_mcp_config(repo_root: Path, *, enabled: bool = True) -> dict[str, Any] | None:
    if not enabled:
        return None
    scripts = repo_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    import mcp_path_predicate  # noqa: WPS433
    import shipwright_paths  # noqa: WPS433

    emit_root = mcp_path_predicate.mcp_emit_repo_root(repo_root)
    server = shipwright_paths.bounded_mcp_server_path(emit_root)
    config_path = shipwright_paths.bounded_mcp_config_path(emit_root, "opencode")
    doc = {
        "adapter_id": "opencode",
        "config_path": str(config_path),
        "mcpServers": {
            "shipwright-bounded": {
                "command": "python3",
                "args": [str(server)],
                "transport": "stdio",
            }
        },
    }
    mcp_path_predicate.validate_build_mcp_config(doc)
    return doc


def portability_trap_contract() -> dict[str, Any]:
    return {
        "tool_permission_mode": TOOL_PERMISSION_MODE,
        "positional_arg_start_index": POSITIONAL_ARG_START_INDEX,
        "instruction_discovery": INSTRUCTION_DISCOVERY,
        "forbidden_instruction_env_vars": [
            "OPENCODE_HOME",
            "OPENCODE_INSTRUCTIONS",
            "HOME",
        ],
    }


def lifecycle_plugin_unsupported_diagnostics() -> list[dict[str, Any]]:
    """Structured diagnostics the TS shim must emit for unsupported events (R28)."""
    out: list[dict[str, Any]] = []
    for row in unsupported_events():
        diag = dict(row["diagnostic"])
        diag["canonical"] = row["canonical"]
        out.append(diag)
    return out
