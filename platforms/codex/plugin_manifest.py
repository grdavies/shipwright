"""Codex native plugin manifest builder and schema check (PRD 349 R20)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REQUIRED_MANIFEST_FIELDS = ("name", "version", "schema_version", "skills", "hooks", "agents")


class ManifestValidationError(ValueError):
    """Raised when a Codex plugin manifest fails schema checks."""


def build_plugin_manifest(
    *,
    version: str,
    skill_ids: list[str],
    hook_events: list[str],
    agents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a Codex native plugin manifest with stable skill identity refs."""
    return {
        "name": "shipwright",
        "version": version,
        "schema_version": "1",
        "description": "Shipwright for Codex (generated)",
        "skills": [{"id": sid, "source": f"core/skills/{sid}"} for sid in skill_ids],
        "hooks": [{"event": ev, "handler": "hooks/codex-hook.py"} for ev in hook_events],
        "agents": agents
        or [
            {
                "id": "shipwright-default",
                "name": "Shipwright",
                "entrypoint": "agents/default.json",
            }
        ],
        "installer": "./scripts/install.py",
    }


def validate_codex_plugin_manifest(manifest: dict[str, Any]) -> list[str]:
    """Return schema violation messages (empty list => pass)."""
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
    skills = manifest.get("skills")
    if not isinstance(skills, list):
        errors.append("skills must be an array")
    else:
        for i, row in enumerate(skills):
            if not isinstance(row, dict):
                errors.append(f"skills[{i}] must be an object")
                continue
            if not row.get("id"):
                errors.append(f"skills[{i}].id required")
            source = str(row.get("source") or "")
            if not source.startswith("core/skills/"):
                errors.append(f"skills[{i}].source must reference core/skills/ (R21)")
            if "body" in row or "content" in row:
                errors.append(f"skills[{i}] must not embed skill body (R21)")
    if not isinstance(manifest.get("hooks"), list):
        errors.append("hooks must be an array")
    agents = manifest.get("agents")
    if not isinstance(agents, list) or not agents:
        errors.append("agents must be a non-empty array")
    return errors


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    errors = validate_codex_plugin_manifest(manifest)
    if errors:
        raise ManifestValidationError("; ".join(errors))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
