#!/usr/bin/env python3
"""Init credential migration and progressive disclosure (PRD 080 phase 23 / R1, R2, R6)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from credentials.ci_declaration import CI_SELECTOR_RELATIVE, ci_selector_path
from credentials.config_surface import PROJECT_ID_PATTERN, validate_project_id
from credentials.platform_matrix import keystore_supported_on_host
from credentials.resolver import repo_slug_from_remote
from credentials.selector_store import default_selector_path
from host_lib import (
    detect_provider_from_url,
    git_remote_url,
    load_workflow_config,
    parse_git_remote_url,
    remote_name,
    resolve_token_env,
)

CONFIGURE_CLI = "python3 scripts/sw-configure.py"
DEFAULT_HOST_REF = "github-work"
DEFAULT_PLANNING_REF = "planning-work"
DEFAULT_MEMORY_REF = "memory-work"
DEFAULT_ENDPOINT = "https://api.github.com"
_GH_ACCOUNT_LINE = re.compile(
    r"Logged in to (?P<host>\S+) account (?P<account>\S+)",
    re.IGNORECASE,
)

AccountDetector = Callable[[Path], tuple["DetectedAccount", ...]]


@dataclass(frozen=True, slots=True)
class DetectedAccount:
    provider: str
    hostname: str
    account: str


@dataclass(frozen=True, slots=True)
class CredentialRefs:
    host: str
    planning: str
    memory: str

    def as_dict(self) -> dict[str, str]:
        return {
            "host": self.host,
            "planning": self.planning,
            "memory": self.memory,
        }


@dataclass(frozen=True, slots=True)
class InitCredentialPlan:
    disclosure: str
    project_id: str
    repo_slug: str
    provider: str
    hostname: str
    credential_refs: CredentialRefs
    accounts: tuple[DetectedAccount, ...]
    legacy_token_env: str | None
    has_project_id: bool
    has_credential_refs: bool
    has_local_selector: bool
    has_ci_declaration: bool
    recommended_backend: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "disclosure": self.disclosure,
            "projectId": self.project_id,
            "repoSlug": self.repo_slug,
            "provider": self.provider,
            "hostname": self.hostname,
            "credentialRefs": self.credential_refs.as_dict(),
            "accounts": [
                {
                    "provider": item.provider,
                    "hostname": item.hostname,
                    "account": item.account,
                }
                for item in self.accounts
            ],
            "legacyTokenEnv": self.legacy_token_env,
            "hasProjectId": self.has_project_id,
            "hasCredentialRefs": self.has_credential_refs,
            "hasLocalSelector": self.has_local_selector,
            "hasCiDeclaration": self.has_ci_declaration,
            "recommendedBackend": self.recommended_backend,
            "multiPrincipalRequired": self.disclosure == "multi",
            "keystoreAvailable": keystore_supported_on_host(),
        }


def default_credential_refs() -> CredentialRefs:
    return CredentialRefs(
        host=DEFAULT_HOST_REF,
        planning=DEFAULT_PLANNING_REF,
        memory=DEFAULT_MEMORY_REF,
    )


def _slug_to_project_id(repo_slug: str, fallback: str) -> str:
    raw = (repo_slug.split("/", 1)[-1] if repo_slug else fallback).lower()
    candidate = re.sub(r"[^a-z0-9-]+", "-", raw)
    candidate = re.sub(r"-{2,}", "-", candidate).strip("-")
    if not candidate or not candidate[0].isalpha():
        candidate = f"proj-{candidate or 'repo'}"
    if not PROJECT_ID_PATTERN.fullmatch(candidate):
        candidate = re.sub(r"[^a-z0-9-]", "", candidate)
        if not candidate or not candidate[0].isalpha():
            candidate = "proj-repo"
    return validate_project_id(candidate)


def _provider_hostname(provider: str, remote_url: str | None) -> tuple[str, str]:
    host = parse_git_remote_url(remote_url or "") if remote_url else ""
    if provider == "github":
        return "github", host or "github.com"
    if provider == "gitlab":
        return "gitlab", host or "gitlab.com"
    if provider == "bitbucket":
        return "bitbucket", host or "bitbucket.org"
    return provider or "none", host or "localhost"


def _recommended_backend(accounts: Sequence[DetectedAccount]) -> str:
    if len(accounts) == 1:
        return "github_cli"
    if not accounts:
        return "environment"
    return "keystore"


def _disclosure_level(accounts: Sequence[DetectedAccount]) -> str:
    if len(accounts) > 1:
        return "multi"
    return "single"


def detect_accounts_from_gh(root: Path) -> tuple[DetectedAccount, ...]:
    proc = subprocess.run(
        ["gh", "auth", "status"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    text = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
    accounts: list[DetectedAccount] = []
    seen: set[tuple[str, str]] = set()
    for line in text.splitlines():
        match = _GH_ACCOUNT_LINE.search(line)
        if not match:
            continue
        hostname = match.group("host").strip()
        account = match.group("account").strip()
        provider = detect_provider_from_url(f"https://{hostname}/")
        key = (hostname, account)
        if key in seen:
            continue
        seen.add(key)
        accounts.append(
            DetectedAccount(
                provider=provider if provider != "none" else "github",
                hostname=hostname,
                account=account,
            )
        )
    return tuple(accounts)


def _config_has_credential_refs(cfg: Mapping[str, Any]) -> bool:
    host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    store = planning.get("store") if isinstance(planning.get("store"), dict) else {}
    issues = store.get("issues") if isinstance(store.get("issues"), dict) else {}
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
    return any(
        isinstance(section.get("credentialRef"), str) and section.get("credentialRef", "").strip()
        for section in (host, issues, memory)
    )


def _legacy_token_env(cfg: Mapping[str, Any]) -> str | None:
    host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
    token_env = host.get("tokenEnv")
    if isinstance(token_env, str) and token_env.strip():
        return token_env.strip()
    return None


def build_init_plan(
    root: Path,
    *,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
    account_detector: AccountDetector | None = None,
) -> InitCredentialPlan:
    cfg = load_workflow_config(root)
    remote = git_remote_url(root, remote_name(cfg)) or ""
    repo_slug = repo_slug_from_remote(remote)
    provider = str((cfg.get("host") or {}).get("provider") or detect_provider_from_url(remote))
    provider_name, hostname = _provider_hostname(provider, remote)
    project_id = str(cfg.get("projectId") or "").strip()
    if not project_id:
        project_id = _slug_to_project_id(repo_slug, root.name)
    detector = account_detector or detect_accounts_from_gh
    accounts = detector(root)
    refs = default_credential_refs()
    selector = selector_path or default_selector_path(xdg_base=xdg_base)
    ci_path = ci_selector_path(root)
    return InitCredentialPlan(
        disclosure=_disclosure_level(accounts),
        project_id=project_id,
        repo_slug=repo_slug,
        provider=provider_name,
        hostname=hostname,
        credential_refs=refs,
        accounts=accounts,
        legacy_token_env=_legacy_token_env(cfg),
        has_project_id=bool(str(cfg.get("projectId") or "").strip()),
        has_credential_refs=_config_has_credential_refs(cfg),
        has_local_selector=selector.is_file(),
        has_ci_declaration=ci_path.is_file(),
        recommended_backend=_recommended_backend(accounts),
    )


def build_selector_entry(
    *,
    backend: str,
    provider: str,
    hostname: str,
    account: str,
    repo_slug: str,
    project_id: str,
    allowed_endpoint: str = DEFAULT_ENDPOINT,
    token_env: str | None = None,
) -> dict[str, object]:
    entry: dict[str, object] = {
        "backend": backend,
        "provider": provider,
        "hostname": hostname,
        "account": account,
        "allowedRepos": [repo_slug] if repo_slug else [],
        "allowedProjectIds": [project_id],
        "allowedEndpoints": [allowed_endpoint],
    }
    if token_env and token_env.strip():
        entry["tokenEnv"] = token_env.strip()
    return entry


def selector_add_command(
    *,
    ref: str,
    backend: str,
    provider: str,
    hostname: str,
    account: str,
    repo_slug: str,
    project_id: str,
    allowed_endpoint: str = DEFAULT_ENDPOINT,
) -> str:
    return (
        f"{CONFIGURE_CLI} credential selector-add "
        f"--ref {ref} "
        f"--backend {backend} "
        f"--provider {provider} "
        f"--hostname {hostname} "
        f"--account {account} "
        f"--allowed-repo {repo_slug} "
        f"--allowed-project-id {project_id} "
        f"--allowed-endpoint {allowed_endpoint}"
    )


def migration_selector_command(plan: InitCredentialPlan, account: DetectedAccount | None = None) -> str:
    selected = account or (plan.accounts[0] if plan.accounts else None)
    account_name = selected.account if selected else "work"
    provider = selected.provider if selected else plan.provider
    hostname = selected.hostname if selected else plan.hostname
    return selector_add_command(
        ref=plan.credential_refs.host,
        backend="environment",
        provider=provider,
        hostname=hostname,
        account=account_name,
        repo_slug=plan.repo_slug,
        project_id=plan.project_id,
    )


def _config_path(root: Path) -> Path:
    return root / ".cursor" / "workflow.config.json"


def _read_config(root: Path) -> dict[str, Any]:
    path = _config_path(root)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_config(root: Path, cfg: dict[str, Any]) -> Path:
    path = _config_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return path


def _default_token_env(provider: str) -> str:
    if provider == "github":
        return "GITHUB_TOKEN"
    if provider == "gitlab":
        return "GITLAB_TOKEN"
    if provider == "bitbucket":
        return "BITBUCKET_TOKEN"
    return ""


def credential_refs_patch(plan: InitCredentialPlan) -> dict[str, Any]:
    refs = plan.credential_refs
    token_env = _default_token_env(plan.provider)
    host_patch: dict[str, Any] = {
        "provider": plan.provider,
        "remote": "origin",
        "credentialRef": refs.host,
    }
    if token_env:
        host_patch["tokenEnv"] = token_env
    return {
        "projectId": plan.project_id,
        "host": host_patch,
        "planning": {
            "store": {
                "issues": {
                    "credentialRef": refs.planning,
                }
            }
        },
        "memory": {
            "credentialRef": refs.memory,
        },
    }


def merge_config_patch(cfg: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(cfg)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            for nested_key, nested_value in value.items():
                if isinstance(nested_value, dict) and isinstance(nested.get(nested_key), dict):
                    inner = dict(nested[nested_key])
                    inner.update(nested_value)
                    nested[nested_key] = inner
                else:
                    nested[nested_key] = nested_value
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _load_selector_document(path: Path) -> dict[str, Any]:
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            entries = payload.get("entries")
            if isinstance(entries, dict):
                return {"version": 1, "entries": dict(entries)}
    return {"version": 1, "entries": {}}


def _configured_provider_for_credential_ref(
    root: Path,
    cfg: Mapping[str, Any],
    ref: str,
    credential_refs: CredentialRefs,
) -> str:
    if ref == credential_refs.host:
        host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
        provider = str(host.get("provider") or "github")
        return provider if provider != "none" else "github"
    if ref == credential_refs.memory:
        memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}
        configured = memory.get("provider")
        if isinstance(configured, str) and configured.strip():
            provider = configured.strip()
            return provider if provider != "none" else "recallium"
        from memory_sot import resolve_memory_provider

        provider = resolve_memory_provider(root, dict(cfg))
        if provider:
            return provider if provider != "none" else "recallium"
        host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
        host_provider = str(host.get("provider") or "github")
        return host_provider if host_provider != "none" else "github"
    if ref == credential_refs.planning:
        from planning_store import _ISSUES_PROVIDER_TO_BROKER, resolve_issues_provider

        issues_provider = str(resolve_issues_provider(dict(cfg)).get("provider") or "github-issues")
        broker = _ISSUES_PROVIDER_TO_BROKER.get(issues_provider, issues_provider)
        return broker if broker not in {"", "none"} else "github"
    return ""


def _entry_provider_matches_ref(
    root: Path,
    cfg: Mapping[str, Any],
    ref: str,
    entry: Mapping[str, object],
    credential_refs: CredentialRefs,
) -> bool:
    configured = _configured_provider_for_credential_ref(root, cfg, ref, credential_refs)
    if not configured:
        return True
    entry_provider = str(entry.get("provider") or "")
    return configured == entry_provider


def _remove_selector_ref(path: Path, ref: str) -> None:
    if not path.is_file():
        return
    document = _load_selector_document(path)
    entries = document.get("entries")
    if not isinstance(entries, dict) or ref not in entries:
        return
    del entries[ref]
    if entries:
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def write_local_selector_entry(
    *,
    ref: str,
    entry: Mapping[str, object],
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
    root: Path | None = None,
    credential_refs: CredentialRefs | None = None,
) -> Path | None:
    path = selector_path or default_selector_path(xdg_base=xdg_base)
    refs = credential_refs or default_credential_refs()
    if root is not None:
        cfg = _read_config(root)
        if not _entry_provider_matches_ref(root, cfg, ref, entry, refs):
            _remove_selector_ref(path, ref)
            return None
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
    document = _load_selector_document(path)
    entries = document.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        document["entries"] = entries
    entries[ref] = dict(entry)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def write_ci_selector_declaration(
    root: Path,
    *,
    entries: Mapping[str, Mapping[str, object]],
    credential_refs: CredentialRefs | None = None,
) -> Path:
    path = ci_selector_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = _load_selector_document(path)
    store = document.setdefault("entries", {})
    if not isinstance(store, dict):
        store = {}
        document["entries"] = store
    refs = credential_refs or default_credential_refs()
    cfg = _read_config(root)
    for ref, entry in entries.items():
        if _entry_provider_matches_ref(root, cfg, ref, entry, refs):
            store[ref] = dict(entry)
        else:
            store.pop(ref, None)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def apply_guided_single_identity(
    root: Path,
    plan: InitCredentialPlan,
    *,
    confirm: bool,
    account: DetectedAccount | None = None,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> dict[str, Any]:
    if plan.disclosure == "multi":
        return {
            "verdict": "halt",
            "disclosure": "multi",
            "accounts": [item.account for item in plan.accounts],
            "hint": (
                "multiple accounts detected; configure keystore or per-reference backends "
                "before applying the guided single-identity path"
            ),
        }
    selected = account or (plan.accounts[0] if plan.accounts else None)
    account_name = selected.account if selected else "work"
    provider = selected.provider if selected else plan.provider
    hostname = selected.hostname if selected else plan.hostname
    backend = plan.recommended_backend
    entry = build_selector_entry(
        backend=backend,
        provider=provider,
        hostname=hostname,
        account=account_name,
        repo_slug=plan.repo_slug,
        project_id=plan.project_id,
    )
    selector_command = selector_add_command(
        ref=plan.credential_refs.host,
        backend=backend,
        provider=provider,
        hostname=hostname,
        account=account_name,
        repo_slug=plan.repo_slug,
        project_id=plan.project_id,
    )
    if not confirm:
        return {
            "verdict": "confirm-required",
            "disclosure": plan.disclosure,
            "selectorCommand": selector_command,
            "wouldWrite": {
                "configPath": str(_config_path(root)),
                "selectorPath": str(selector_path or default_selector_path(xdg_base=xdg_base)),
                "credentialRefs": plan.credential_refs.as_dict(),
                "projectId": plan.project_id,
            },
        }
    cfg = merge_config_patch(_read_config(root), credential_refs_patch(plan))
    config_path = _write_config(root, cfg)
    selector_written = write_local_selector_entry(
        ref=plan.credential_refs.host,
        entry=entry,
        selector_path=selector_path,
        xdg_base=xdg_base,
        root=root,
        credential_refs=plan.credential_refs,
    )
    active_selector = selector_written or selector_path or default_selector_path(xdg_base=xdg_base)
    for ref_name in (plan.credential_refs.planning, plan.credential_refs.memory):
        write_local_selector_entry(
            ref=ref_name,
            entry=entry,
            selector_path=active_selector,
            xdg_base=xdg_base,
            root=root,
            credential_refs=plan.credential_refs,
        )
    return {
        "verdict": "ok",
        "disclosure": plan.disclosure,
        "configPath": str(config_path),
        "selectorPath": str(active_selector),
        "selectorCommand": selector_command,
        "projectId": plan.project_id,
        "credentialRefs": plan.credential_refs.as_dict(),
        "userLevelWriteException": True,
    }


def offer_legacy_migration(
    root: Path,
    plan: InitCredentialPlan,
    *,
    confirm: bool,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> dict[str, Any]:
    if not plan.legacy_token_env:
        return {
            "verdict": "noop",
            "reason": "no-legacy-token-env",
        }
    selector_command = migration_selector_command(plan)
    if not confirm:
        return {
            "verdict": "confirm-required",
            "legacyTokenEnv": plan.legacy_token_env,
            "selectorCommand": selector_command,
            "migrationPrompt": (
                f"legacy host.tokenEnv {plan.legacy_token_env!r} detected; "
                "migrate to credentialRef with consent before cutover"
            ),
        }
    cfg = _read_config(root)
    host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
    host = dict(host)
    host["credentialRef"] = plan.credential_refs.host
    cfg = merge_config_patch(cfg, {"projectId": plan.project_id, "host": host})
    config_path = _write_config(root, cfg)
    selected = plan.accounts[0] if plan.accounts else None
    account_name = selected.account if selected else "work"
    provider = selected.provider if selected else plan.provider
    hostname = selected.hostname if selected else plan.hostname
    entry = build_selector_entry(
        backend="environment",
        provider=provider,
        hostname=hostname,
        account=account_name,
        repo_slug=plan.repo_slug,
        project_id=plan.project_id,
    )
    selector_written = write_local_selector_entry(
        ref=plan.credential_refs.host,
        entry=entry,
        selector_path=selector_path,
        xdg_base=xdg_base,
    )
    return {
        "verdict": "ok",
        "legacyTokenEnv": plan.legacy_token_env,
        "selectorCommand": selector_command,
        "configPath": str(config_path),
        "selectorPath": str(selector_written),
        "credentialRef": plan.credential_refs.host,
    }


def offer_ci_env_declaration(
    root: Path,
    plan: InitCredentialPlan,
    *,
    confirm: bool,
    token_env: str | None = None,
) -> dict[str, Any]:
    cfg = _read_config(root)
    host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
    env_name = token_env or resolve_token_env(host, plan.provider) or "GITHUB_TOKEN"
    selected = plan.accounts[0] if plan.accounts else None
    account_name = selected.account if selected else "work"
    provider = selected.provider if selected else plan.provider
    hostname = selected.hostname if selected else plan.hostname
    entry = build_selector_entry(
        backend="environment",
        provider=provider,
        hostname=hostname,
        account=account_name,
        repo_slug=plan.repo_slug,
        project_id=plan.project_id,
    )
    refs = plan.credential_refs
    if not confirm:
        return {
            "verdict": "confirm-required",
            "ciSelectorPath": str(ci_selector_path(root)),
            "tokenEnv": env_name,
            "offer": (
                "declare an Actions env-backend selector so CI resolves without a "
                "machine-local selector file"
            ),
            "wouldWriteRefs": refs.as_dict(),
        }
    written = write_ci_selector_declaration(
        root,
        entries={
            refs.host: entry,
            refs.planning: entry,
            refs.memory: entry,
        },
        credential_refs=refs,
    )
    cfg = merge_config_patch(_read_config(root), {"host": {"tokenEnv": env_name}})
    _write_config(root, cfg)
    return {
        "verdict": "ok",
        "ciSelectorPath": str(written),
        "ciSelectorRelative": CI_SELECTOR_RELATIVE.as_posix(),
        "tokenEnv": env_name,
        "credentialRefs": refs.as_dict(),
    }


def selector_add(
    *,
    ref: str,
    backend: str,
    provider: str,
    hostname: str,
    account: str,
    allowed_repo: str,
    allowed_project_id: str,
    allowed_endpoint: str,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> dict[str, Any]:
    entry = build_selector_entry(
        backend=backend,
        provider=provider,
        hostname=hostname,
        account=account,
        repo_slug=allowed_repo,
        project_id=allowed_project_id,
        allowed_endpoint=allowed_endpoint,
    )
    path = write_local_selector_entry(
        ref=ref,
        entry=entry,
        selector_path=selector_path,
        xdg_base=xdg_base,
    )
    return {"verdict": "ok", "ref": ref, "path": str(path)}


def credential_patch_for_draft(root: Path) -> dict[str, Any]:
    plan = build_init_plan(root)
    if plan.disclosure == "multi":
        return {}
    return credential_refs_patch(plan)
