#!/usr/bin/env python3
"""Cross-project trusted-source authorization resolver (PRD 082 R32)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from host_lib import load_workflow_config
from planning_store import PROJECT_KEY_PATTERN

TRUSTED_SOURCES_CONFIG_KEY = ("memory", "crossProjectTrustedSources")
PAYLOAD_TRUST_TEST_FLAG = "allowPayloadTrustedSources"


def harness_allows_payload_trust() -> bool:
    """Test-only switch — inert outside the harness runner (PRD 082 R32)."""
    return os.environ.get("SW_HARNESS") == "1"


def _planning_store_section(cfg: dict[str, Any]) -> dict[str, Any]:
    planning = cfg.get("planning")
    if not isinstance(planning, dict):
        return {}
    store = planning.get("store")
    return store if isinstance(store, dict) else {}


def caller_project_key(root: Path, cfg: dict[str, Any] | None = None) -> str | None:
    """Caller project key is always resolved from the caller worktree config."""
    if cfg is None:
        cfg = load_workflow_config(root)
    store = _planning_store_section(cfg)
    raw = store.get("projectKey")
    if not isinstance(raw, str) or not raw.strip():
        return None
    key = raw.strip()
    if not PROJECT_KEY_PATTERN.fullmatch(key):
        return None
    return key


def config_trusted_sources(cfg: dict[str, Any]) -> list[str]:
    memory = cfg.get("memory")
    if not isinstance(memory, dict):
        return []
    raw = memory.get(TRUSTED_SOURCES_CONFIG_KEY[1])
    if not isinstance(raw, list):
        return []
    trusted: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        key = item.strip()
        if PROJECT_KEY_PATTERN.fullmatch(key):
            trusted.append(key)
    return sorted(set(trusted))


def _reject_widening(config_trusted: set[str], payload_trusted: set[str]) -> bool:
    return bool(payload_trusted - config_trusted)


def resolve_trusted_sources(
    root: Path,
    *,
    payload_authorized_projects: list[str] | None = None,
    allow_payload_trust: bool | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve caller key and the effective trusted-source set from worktree config."""
    if cfg is None:
        cfg = load_workflow_config(root)
    caller = caller_project_key(root, cfg)
    if caller is None:
        return {"verdict": "fail", "error": "missing-caller-project-key"}

    configured = set(config_trusted_sources(cfg))
    payload_allowed = harness_allows_payload_trust() and (
        allow_payload_trust is not False if allow_payload_trust is not None else True
    )

    payload_set: set[str] = set()
    if payload_authorized_projects:
        for item in payload_authorized_projects:
            if not isinstance(item, str):
                continue
            key = item.strip()
            if PROJECT_KEY_PATTERN.fullmatch(key):
                payload_set.add(key)

    if payload_set and _reject_widening(configured, payload_set):
        return {
            "verdict": "fail",
            "error": "payload-widening-rejected",
            "callerProjectKey": caller,
            "configuredTrustedSources": sorted(configured),
        }

    if payload_allowed and payload_set:
        effective = payload_set & configured
    else:
        effective = configured

    return {
        "verdict": "pass",
        "callerProjectKey": caller,
        "configuredTrustedSources": sorted(configured),
        "effectiveTrustedSources": sorted(effective),
        "payloadTrustApplied": bool(payload_allowed and payload_set),
    }


def authorize_cross_project(
    caller_key: str,
    source_key: str,
    effective_trusted_sources: set[str] | list[str] | None,
) -> bool:
    if caller_key == source_key:
        return True
    trusted = set(effective_trusted_sources or [])
    return source_key in trusted


def cross_project_dereference_blocked(ptr: dict[str, Any], *, cross_project: bool) -> bool:
    """Secret and personal records are never dereferenced across projects."""
    if not cross_project:
        return False
    sensitivity = str(ptr.get("sensitivity", "")).strip().lower()
    if sensitivity in {"secret", "private"}:
        return True
    category = str(ptr.get("category", "")).strip().lower()
    if category == "personal":
        return True
    return False
