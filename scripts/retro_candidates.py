#!/usr/bin/env python3
"""PRD 337 R18 — retro learning candidate posture classification."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sw_scripts_resolve import is_shipwright_self_repo

PLUGIN_SELF_PATH_PREFIXES = (
    ".cursor/",
    "core/",
    "dist/",
    "hooks/",
    "platforms/",
    "providers/",
    "rules/",
    "scripts/",
    "sw/",
)
PLUGIN_FRICTION_CATEGORIES = frozenset(
    {
        "orchestrator",
        "plugin-process",
        "ship-loop",
        "workflow-tool",
    }
)
PRODUCT_FRICTION_CATEGORIES = frozenset(
    {
        "api",
        "application",
        "product-code",
        "ui",
    }
)
POSTURE_CONSUMER = "consumer"
POSTURE_PLUGIN_SELF = "plugin-self"
FRICTION_PRODUCT = "product"
FRICTION_PLUGIN_SELF = "plugin-self"


def resolve_repo_posture(root: Path) -> str:
    """Return consumer vs plugin-self repo posture for retro routing."""
    return POSTURE_PLUGIN_SELF if is_shipwright_self_repo(root) else POSTURE_CONSUMER


def _is_plugin_path(path: str) -> bool:
    normalized = path.strip().lstrip("./")
    return any(normalized.startswith(prefix) for prefix in PLUGIN_SELF_PATH_PREFIXES)


def classify_friction_scope(item: dict[str, Any]) -> str:
    """Classify a retro painful item as product or plugin-self friction."""
    explicit = str(item.get("gapClass") or item.get("frictionScope") or "").strip().lower()
    if explicit in {FRICTION_PLUGIN_SELF, "plugin", "process"}:
        return FRICTION_PLUGIN_SELF
    if explicit in {FRICTION_PRODUCT, "product-code", "application"}:
        return FRICTION_PRODUCT

    category = str(item.get("category") or "").strip().lower()
    if category in PLUGIN_FRICTION_CATEGORIES:
        return FRICTION_PLUGIN_SELF
    if category in PRODUCT_FRICTION_CATEGORIES:
        return FRICTION_PRODUCT

    related = item.get("relatedFiles")
    if isinstance(related, list) and related:
        plugin_hits = sum(1 for path in related if _is_plugin_path(str(path)))
        product_hits = len(related) - plugin_hits
        if plugin_hits and not product_hits:
            return FRICTION_PLUGIN_SELF
        if product_hits and not plugin_hits:
            return FRICTION_PRODUCT
        if plugin_hits > product_hits:
            return FRICTION_PLUGIN_SELF

    return FRICTION_PRODUCT


def select_learning_candidates(
    items: list[Any],
    *,
    posture: str,
) -> dict[str, Any]:
    """Scope retro/compound learning candidates by repository posture (R18)."""
    candidates: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in {"well", "painful", "change"}:
            continue
        scope = classify_friction_scope(item) if kind == "painful" else FRICTION_PRODUCT
        if posture == POSTURE_CONSUMER and scope == FRICTION_PLUGIN_SELF and kind == "painful":
            excluded.append(
                {
                    "itemId": item.get("itemId"),
                    "kind": kind,
                    "reason": "plugin-friction-excluded-consumer",
                    "scope": scope,
                }
            )
            continue
        if posture == POSTURE_PLUGIN_SELF:
            priority = 1 if scope == FRICTION_PLUGIN_SELF or kind in {"change", "well"} else 0
        else:
            priority = 1 if scope == FRICTION_PRODUCT or kind in {"change", "well"} else 0
        candidates.append(
            {
                **item,
                "learningScope": scope,
                "priority": priority,
            }
        )
    candidates.sort(
        key=lambda row: (-int(row.get("priority") or 0), str(row.get("itemId") or "")),
    )
    return {
        "candidates": candidates,
        "excluded": excluded,
        "posture": posture,
    }
