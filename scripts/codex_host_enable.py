#!/usr/bin/env python3
"""Register and enable the Codex plugin on the machine (personal marketplace + config)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


PLUGIN_NAME = "shipwright"
MARKETPLACE_NAME = "personal"
PLUGIN_SOURCE_PATH = "./.codex/plugins/shipwright"
PLUGIN_CONFIG_SECTION = '[plugins."shipwright@personal"]'
MARKETPLACE_REL = Path(".agents") / "plugins" / "marketplace.json"
CODEX_CONFIG_REL = Path(".codex") / "config.toml"


def personal_marketplace_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / MARKETPLACE_REL


def codex_config_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / CODEX_CONFIG_REL


def plan_enablement_paths(home: Path | None = None) -> list[str]:
    root = home or Path.home()
    return [
        str(personal_marketplace_path(root).resolve()),
        str(codex_config_path(root).resolve()),
    ]


def shipwright_marketplace_entry() -> dict[str, Any]:
    return {
        "name": PLUGIN_NAME,
        "source": {"source": "local", "path": PLUGIN_SOURCE_PATH},
        "policy": {
            "installation": "INSTALLED_BY_DEFAULT",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def upsert_personal_marketplace(path: Path) -> str:
    """Merge the Shipwright entry into the personal marketplace catalog.

    Returns ``created``, ``updated``, or ``unchanged``.
    """
    entry = shipwright_marketplace_entry()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
    else:
        data = {}

    plugins = data.get("plugins")
    if not isinstance(plugins, list):
        plugins = []
    changed = False
    replaced = False
    next_plugins: list[Any] = []
    for row in plugins:
        if isinstance(row, dict) and str(row.get("name") or "") == PLUGIN_NAME:
            if row != entry:
                next_plugins.append(entry)
                changed = True
            else:
                next_plugins.append(row)
            replaced = True
        else:
            next_plugins.append(row)
    if not replaced:
        next_plugins.append(entry)
        changed = True

    next_data = {
        "name": str(data.get("name") or MARKETPLACE_NAME),
        "interface": {"displayName": "Personal"},
        "plugins": next_plugins,
    }
    existing_interface = data.get("interface")
    if isinstance(existing_interface, dict) and existing_interface.get("displayName"):
        next_data["interface"] = {
            **existing_interface,
            "displayName": existing_interface.get("displayName") or "Personal",
        }

    existed = path.is_file()
    if (
        not changed
        and existed
        and data.get("name") == next_data["name"]
        and (data.get("interface") or {}).get("displayName")
    ):
        return "unchanged"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(next_data, indent=2) + "\n", encoding="utf-8")
    return "updated" if existed else "created"


def enable_plugin_in_config(path: Path) -> str:
    """Ensure ``[plugins."shipwright@personal"] enabled = true`` in config.toml."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    if PLUGIN_CONFIG_SECTION in text:
        pattern = re.compile(
            rf"({re.escape(PLUGIN_CONFIG_SECTION)}\n)(.*?)(?=\n\[|\Z)",
            re.DOTALL,
        )
        match = pattern.search(text)
        if match:
            body = match.group(2)
            if re.search(r"(?m)^enabled\s*=\s*true\s*$", body):
                return "unchanged"
            if re.search(r"(?m)^enabled\s*=", body):
                new_body = re.sub(r"(?m)^enabled\s*=\s*.*$", "enabled = true", body, count=1)
            else:
                new_body = "enabled = true\n" + body
            path.write_text(text[: match.start()] + match.group(1) + new_body + text[match.end() :], encoding="utf-8")
            return "updated"
        return "unchanged"

    addition = f"{PLUGIN_CONFIG_SECTION}\nenabled = true\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if text:
        if not text.endswith("\n"):
            text += "\n"
        path.write_text(text + "\n" + addition, encoding="utf-8")
        return "updated"
    path.write_text(addition, encoding="utf-8")
    return "created"


def enable_codex_host(*, home: Path | None = None) -> dict[str, Any]:
    """Write marketplace catalog + config.toml enablement without requiring a ``codex`` CLI."""
    root = home or Path.home()
    market = personal_marketplace_path(root)
    config = codex_config_path(root)
    market_action = upsert_personal_marketplace(market)
    config_action = enable_plugin_in_config(config)
    return {
        "verdict": "pass",
        "marketplace": str(market),
        "marketplaceAction": market_action,
        "config": str(config),
        "configAction": config_action,
    }
