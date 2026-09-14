"""Codex native plugin manifest builder and schema check (PRD 349 R20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_MANIFEST_FIELDS = ("name", "version", "description", "skills", "hooks", "interface")
NATIVE_SKILLS_PATH = "./skills/"
NATIVE_HOOKS_PATH = "./hooks/hooks.json"


class ManifestValidationError(ValueError):
    """Raised when a Codex plugin manifest fails schema checks."""


def build_plugin_manifest(
    *,
    version: str,
    skill_ids: list[str],
    hook_events: list[str],
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a Codex-desktop-native plugin.json (skills/hooks as relative paths)."""
    _ = (skill_ids, hook_events, agents)  # identity lives in adapter sidecar + skills/index.json
    return {
        "name": "shipwright",
        "version": version,
        "description": "Shipwright for Codex: frozen specs, a gated ship loop, and compounding memory.",
        "skills": NATIVE_SKILLS_PATH,
        "hooks": NATIVE_HOOKS_PATH,
        "interface": {
            "displayName": "Shipwright",
            "shortDescription": "Frozen specs, gated ship loop, compounding memory",
            "developerName": "Shipwright",
            "category": "Productivity",
            "capabilities": ["Read", "Write"],
        },
    }


def build_adapter_manifest(
    *,
    version: str,
    skill_ids: list[str],
    command_ids: list[str],
    hook_events: list[str],
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Shipwright-internal identity refs — not read by Codex desktop."""
    return {
        "name": "shipwright",
        "version": version,
        "schema_version": "1",
        "skills": [{"id": sid, "source": f"core/skills/{sid}"} for sid in skill_ids],
        "commands": [{"id": cid, "source": f"core/commands/{cid}.md"} for cid in command_ids],
        "hooks": [{"event": ev, "handler": "hooks/codex-hook.py"} for ev in hook_events],
        "agents": agents
        or [
            {
                "id": "shipwright-default",
                "name": "Shipwright",
                "entrypoint": "agents/default.json",
            }
        ],
    }


def build_native_hooks_document(handlers: list[dict[str, str]]) -> dict[str, Any]:
    """Codex desktop hooks.json — canonical event names as keys."""
    hooks: dict[str, list[dict[str, Any]]] = {}
    for row in handlers:
        canonical = str(row.get("canonical") or "").strip()
        if not canonical:
            continue
        hooks[canonical] = [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 ${PLUGIN_ROOT}/hooks/codex-hook.py",
                        "statusMessage": f"Shipwright {canonical}",
                    }
                ]
            }
        ]
    return {"hooks": hooks}


def validate_codex_plugin_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return schema violation messages for the native Codex plugin.json (empty => pass)."""
    errors: list[str] = []
    if not isinstance(manifest, dict):
        return ["manifest must be an object"]
    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            errors.append(f"missing required field: {field}")
    if manifest.get("name") != "shipwright":
        errors.append("name must be 'shipwright'")
    if not isinstance(manifest.get("version"), str) or not str(manifest.get("version")).strip():
        errors.append("version must be a non-empty string")
    if manifest.get("skills") != NATIVE_SKILLS_PATH:
        errors.append(f"skills must be {NATIVE_SKILLS_PATH!r}")
    if manifest.get("hooks") != NATIVE_HOOKS_PATH:
        errors.append(f"hooks must be {NATIVE_HOOKS_PATH!r}")
    interface = manifest.get("interface")
    if not isinstance(interface, dict):
        errors.append("interface must be an object")
    else:
        if not str(interface.get("displayName") or "").strip():
            errors.append("interface.displayName required")
        if interface.get("category") != "Productivity":
            errors.append("interface.category must be 'Productivity'")
    if "body" in manifest or "content" in manifest:
        errors.append("manifest must not embed skill body (R21)")
    return errors


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    errors = validate_codex_plugin_manifest(manifest)
    if errors:
        raise ManifestValidationError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
