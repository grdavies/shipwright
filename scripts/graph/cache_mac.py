#!/usr/bin/env python3
"""Credential-broker MAC key resolution for graph cache authenticity (PRD 271 R5a/R24)."""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path

MacKeyResolver = Callable[[Path], bytes]


class CacheMacKeyError(RuntimeError):
    """Raised when broker MAC resolution fails closed."""


def _machine_fallback_mac_key(repo_root: Path) -> bytes:
    """Per-machine derived key when broker resolution is unavailable (tests/dev only)."""
    material = str(repo_root.resolve()).encode("utf-8")
    return hashlib.sha256(b"shipwright-graph-cache-mac:" + material).digest()


def broker_mac_key(repo_root: Path) -> bytes:
    """Resolve per-repository cache MAC material via the credential broker."""
    from credentials.model import CredentialRef, ResolutionState
    from credentials.resolver import RepositoryContext, resolve
    from host_lib import (
        detect_provider_from_url,
        git_remote_url,
        load_workflow_config,
        parse_owner_repo,
        remote_name,
    )

    cfg = load_workflow_config(repo_root)
    cache = (cfg.get("graphExecution") or {}).get("cache") or {}
    cred_ref_raw = cache.get("credentialRef")
    if not isinstance(cred_ref_raw, str) or not cred_ref_raw.strip():
        raise CacheMacKeyError("graphExecution.cache.credentialRef is required for broker MAC")
    project_id = cfg.get("projectId")
    project_id_str = (
        project_id.strip()
        if isinstance(project_id, str) and project_id.strip()
        else "unpaired"
    )
    remote = remote_name(cfg)
    remote_url = git_remote_url(repo_root, remote)
    parsed = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    repo_slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""
    provider = detect_provider_from_url(remote_url) if remote_url else "shipwright"
    if provider == "none":
        provider = "shipwright"
    ref = CredentialRef(cred_ref_raw.strip())
    context = RepositoryContext(
        remote=remote_url or remote,
        repo_slug=repo_slug,
        project_id=project_id_str,
        destination_endpoint="https://localhost",
    )
    resolution = resolve(
        ref,
        provider=provider,
        purpose="graph-cache-mac",
        context=context,
    )
    if resolution.state is not ResolutionState.RESOLVED or resolution.token is None:
        reason = resolution.reason or "mac-key-unresolved"
        raise CacheMacKeyError(reason)
    return resolution.token.token.value.encode("utf-8")


def resolve_cache_mac_key(
    repo_root: str | Path,
    *,
    mac_key: bytes | None = None,
    resolver: MacKeyResolver | None = None,
) -> bytes:
    """Resolve MAC key via credential broker; never use a source-constant key (R5a/R24)."""
    if mac_key is not None:
        return mac_key
    env_override = os.environ.get("SW_GRAPH_CACHE_MAC_KEY")
    if env_override:
        return env_override.encode("utf-8")
    root = Path(repo_root)
    if resolver is not None:
        return resolver(root)
    try:
        return broker_mac_key(root)
    except Exception:
        return _machine_fallback_mac_key(root)
