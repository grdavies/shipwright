#!/usr/bin/env python3
"""Workflow extension feature flags and operator-surface gates (PRD 280 R20–R22)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

EXTENSION_FLAGS = (
    "externalIntake",
    "handoffBundle",
    "packageSdk",
)

FLAG_ALIASES = {
    "external-intake": "externalIntake",
    "external_intake": "externalIntake",
    "handoff-bundle": "handoffBundle",
    "handoff_bundle": "handoffBundle",
    "package-sdk": "packageSdk",
    "package_sdk": "packageSdk",
    "workflow-pack-sdk": "packageSdk",
}


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return {}


def normalize_flag_name(name: str) -> str:
    key = str(name or "").strip()
    if key in EXTENSION_FLAGS:
        return key
    return FLAG_ALIASES.get(key, key)


def extension_flags(cfg: Mapping[str, Any] | None = None, *, root: Path | None = None) -> dict[str, bool]:
    """Return workflow.extensions.* flags (default false when omitted)."""
    if cfg is None:
        cfg = load_workflow_config(root or Path.cwd())
    block = cfg.get("workflow") if isinstance(cfg, Mapping) else None
    extensions = block.get("extensions") if isinstance(block, Mapping) else None
    raw = extensions if isinstance(extensions, Mapping) else {}
    return {flag: bool(raw.get(flag, False)) for flag in EXTENSION_FLAGS}


def extension_enabled(
    flag: str,
    *,
    root: Path | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> bool:
    """True when the named extension flag is enabled.

    `SW_WORKFLOW_EXTENSIONS=1` enables all flags (fixture/CI harness override).
    Per-flag env `SW_WORKFLOW_EXTENSION_<FLAG>=1` enables a single flag.
    """
    normalized = normalize_flag_name(flag)
    if normalized not in EXTENSION_FLAGS:
        raise ValueError(f"unknown workflow extension flag: {flag}")
    if os.environ.get("SW_WORKFLOW_EXTENSIONS", "").strip() in {"1", "true", "TRUE", "yes"}:
        return True
    env_key = f"SW_WORKFLOW_EXTENSION_{normalized.upper()}"
    if os.environ.get(env_key, "").strip() in {"1", "true", "TRUE", "yes"}:
        return True
    return bool(extension_flags(cfg, root=root).get(normalized, False))


def require_extension(
    flag: str,
    *,
    root: Path | None = None,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return a typed halt payload when the extension flag is disabled; else None."""
    normalized = normalize_flag_name(flag)
    if extension_enabled(normalized, root=root, cfg=cfg):
        return None
    return {
        "verdict": "halt",
        "error": "workflow-extensions:disabled",
        "flag": f"workflow.extensions.{normalized}",
        "message": (
            f"Extension '{normalized}' is disabled. Set workflow.extensions.{normalized}=true "
            "in .cursor/workflow.config.json after cutover evidence (PRD 280)."
        ),
    }
