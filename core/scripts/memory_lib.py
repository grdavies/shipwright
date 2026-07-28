#!/usr/bin/env python3
"""Memory provider credential resolution (PRD 080 phase 21 / R1)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from credentials.model import CredentialRef, Resolution, ResolvedToken, Secret
from credentials.resolver import RepositoryContext, resolve
from host_lib import git_remote_url, load_workflow_config, parse_owner_repo, remote_name
from memory_sot import resolve_memory_provider

DEFAULT_RECALLIUM_BASE = "http://localhost:8001"


def memory_section(cfg: dict[str, Any]) -> dict[str, Any]:
    memory = cfg.get("memory")
    return memory if isinstance(memory, dict) else {}


def resolve_memory_token_env(cfg: dict[str, Any], memory_provider: str = "") -> str:
    """Return an explicitly configured memory tokenEnv only — no implicit provider defaults."""
    _ = memory_provider
    memory = memory_section(cfg)
    token_env = memory.get("tokenEnv")
    if isinstance(token_env, str) and token_env.strip():
        return token_env.strip()
    return ""


def memory_rest_base(cfg: dict[str, Any]) -> str:
    memory = memory_section(cfg)
    connection = memory.get("connection")
    if isinstance(connection, dict):
        raw = connection.get("restBaseUrl")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    return DEFAULT_RECALLIUM_BASE


def resolve_memory_credential(
    root: Path,
    *,
    memory_provider: str | None = None,
    destination_endpoint: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> Resolution:
    """Resolve the memory provider credential through the broker (tri-state)."""
    resolved_cfg = cfg if cfg is not None else load_workflow_config(root)
    provider = memory_provider or resolve_memory_provider(root, resolved_cfg) or "recallium"
    memory = memory_section(resolved_cfg)
    cred_ref_raw = memory.get("credentialRef")
    token_env = resolve_memory_token_env(resolved_cfg, provider)
    api_base = destination_endpoint or memory_rest_base(resolved_cfg)
    project_id = resolved_cfg.get("projectId")
    project_id_str = (
        project_id.strip() if isinstance(project_id, str) and project_id.strip() else "unpaired"
    )
    remote = remote_name(resolved_cfg)
    remote_url = git_remote_url(root, remote)
    parsed = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    repo_slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""

    if isinstance(cred_ref_raw, str) and cred_ref_raw.strip():
        ref = CredentialRef(cred_ref_raw.strip())
        context = RepositoryContext(
            remote=remote_url or remote,
            repo_slug=repo_slug,
            project_id=project_id_str,
            destination_endpoint=api_base,
        )
        return resolve(
            ref,
            provider=provider,
            purpose="memory",
            context=context,
        )

    if token_env:
        value = os.environ.get(token_env, "")
        alias_ref = CredentialRef(f"tokenEnv:{token_env}")
        if value.strip():
            return Resolution.resolved(alias_ref, ResolvedToken(Secret(value)))
        return Resolution.unresolved(alias_ref, reason="missing-token")

    return Resolution.explicitly_no_auth(
        CredentialRef("memory-unauthenticated"),
        reason="no-memory-credential",
    )
