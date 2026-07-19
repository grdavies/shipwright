#!/usr/bin/env python3
"""Task spawn model allowlist enforcement (PRD 073 R6/R7)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

ALLOWLIST_REL = Path("core/sw-reference/task-model-allowlist.json")
CAUSE_NOT_ALLOWLISTED = "binding:model-not-allowlisted"
CAUSE_ALLOWLIST_MISSING = "binding:allowlist-missing"


@dataclass(frozen=True)
class TaskModelAllowlist:
    allowed: frozenset[str]
    aliases: dict[str, str]


def allowlist_path(root: Path | None = None) -> Path:
    base = root if root is not None else Path(__file__).resolve().parent.parent
    return base / ALLOWLIST_REL


def load_task_model_allowlist(root: Path | None = None) -> TaskModelAllowlist:
    path = allowlist_path(root)
    if not path.is_file():
        return TaskModelAllowlist(frozenset(), {})
    doc = json.loads(path.read_text(encoding="utf-8"))
    raw_allowed = doc.get("allowed", [])
    raw_aliases = doc.get("aliases", {})
    allowed = frozenset(str(item) for item in raw_allowed if isinstance(item, str) and item.strip())
    aliases: dict[str, str] = {}
    if isinstance(raw_aliases, dict):
        for key, value in raw_aliases.items():
            if isinstance(key, str) and isinstance(value, str) and key.strip() and value.strip():
                aliases[key.strip()] = value.strip()
    return TaskModelAllowlist(allowed=allowed, aliases=aliases)


def canonicalize_task_model_id(model_id: str, allowlist: TaskModelAllowlist) -> tuple[str | None, str | None]:
    """Return (canonical_id, alias_from) or (None, None) when not allowlisted."""
    mid = (model_id or "").strip()
    if not mid:
        return None, None
    if mid in allowlist.allowed:
        return mid, None
    alias_target = allowlist.aliases.get(mid)
    if alias_target and alias_target in allowlist.allowed:
        return alias_target, mid
    return None, None


def enforce_task_model_allowlist(model_id: str, *, root: Path | None = None) -> dict:
    """Fail-closed allowlist gate for concrete Task spawn model IDs."""
    allowlist = load_task_model_allowlist(root)
    if not allowlist.allowed:
        return {
            "verdict": "fail",
            "cause": CAUSE_ALLOWLIST_MISSING,
            "modelId": model_id,
            "retryable": False,
            "remediation": (
                f"missing or empty Task model allowlist at {ALLOWLIST_REL.as_posix()}; "
                "restore core/sw-reference/task-model-allowlist.json"
            ),
        }

    canonical, alias_from = canonicalize_task_model_id(model_id, allowlist)
    if canonical is None:
        return {
            "verdict": "fail",
            "cause": CAUSE_NOT_ALLOWLISTED,
            "modelId": model_id,
            "retryable": False,
            "remediation": (
                f"model {model_id!r} is not on the Task spawn allowlist "
                f"({ALLOWLIST_REL.as_posix()}); map via models.tiers or add an alias"
            ),
        }

    payload: dict = {"verdict": "pass", "modelId": canonical}
    if alias_from:
        payload["aliasFrom"] = alias_from
    return payload
