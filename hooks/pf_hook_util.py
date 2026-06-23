"""Shared helpers for phase-flow v2 Cursor hooks."""

from __future__ import annotations

import json
from pathlib import Path

_ALLOWLIST_REL = (".cursor/pf-memory-rule-allowlist.json", "pf-memory-rule-allowlist.json")


def read_stdin_json() -> dict:
    import sys

    try:
        text = sys.stdin.read()
        return json.loads(text) if text.strip() else {}
    except (OSError, ValueError):
        return {}


def workspace_root(payload: dict) -> Path:
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        for root in roots:
            if isinstance(root, str) and root.strip():
                candidate = Path(root)
                if candidate.is_dir():
                    return candidate
    return Path.cwd()


def load_config(root: Path) -> dict:
    for path in (root / ".cursor" / "workflow.config.json", root / "workflow.config.json"):
        try:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return {}


def load_allowlist(root: Path) -> tuple[str, set[str] | None]:
    """Returns (status, allowlist). status: absent | ok | corrupt."""
    for rel in _ALLOWLIST_REL:
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return "ok", {str(x) for x in data}
            except (OSError, ValueError):
                return "corrupt", None
    return "absent", None


def filter_rules_by_allowlist(rules: list[dict], allowlist_status: str, allowlist: set[str] | None) -> list[dict]:
    if allowlist_status != "ok" or allowlist is None:
        return rules
    return [
        r
        for r in rules
        if str(r.get("id", "")) in allowlist or r.get("summary", "") in allowlist
    ]


def guardrails_allow_empty(config: dict) -> bool:
    memory = config.get("memory", {}) if isinstance(config, dict) else {}
    guardrails = memory.get("guardrails", {}) if isinstance(memory, dict) else {}
    return bool(guardrails.get("allowEmptyRules", False))
