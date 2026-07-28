"""RepositoryContext factory and non-secret context envelope (PRD 080 phase 12 / R9)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Mapping, Sequence
from typing import Any

from credentials.resolver import RepositoryContext as ResolverRepositoryContext
from credentials.resolver import repo_slug_from_remote
from host_lib import git_remote_url, load_workflow_config, remote_name

CONTEXT_ENVELOPE_ENV = "SW_CONTEXT_ENVELOPE"
ENVELOPE_VERSION = 1

_SECRET_KEY_RE = re.compile(
    r"(token|secret|password|credential|authorization|api[_-]?key)",
    re.IGNORECASE,
)
_BLOCKED_ENVELOPE_KEYS = frozenset(
    {
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GH_ENTERPRISE_TOKEN",
        "GITHUB_ENTERPRISE_TOKEN",
        "GITLAB_TOKEN",
        "BITBUCKET_TOKEN",
        "SW_PLANNING_ISSUES_TOKEN",
    }
)
_ALLOWED_ENVELOPE_KEYS = frozenset(
    {
        "version",
        "root",
        "projectId",
        "worktreeId",
        "planningAuthority",
        "credentialRefs",
        "memoryNamespace",
        "policyOverrides",
        "runId",
        "remote",
        "repoSlug",
        "destinationEndpoint",
    }
)
_SECRET_VALUE_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9\-]{20,})"
)


class RepositoryContextError(ValueError):
    """Invalid repository context construction or envelope handling."""


class RootInvariantError(RepositoryContextError):
    """Root path no longer matches the bound repository context."""


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    """Explicit non-secret repository identity for broker scope and child dispatch."""

    root: str
    project_id: str
    worktree_id: str
    planning_authority: str
    credential_refs: tuple[str, ...]
    memory_namespace: str
    policy_overrides: tuple[tuple[str, str], ...]
    run_id: str | None
    remote: str
    repo_slug: str
    destination_endpoint: str
    _root_at_bind: str

    def assert_root_invariant(self) -> None:
        bound = Path(self._root_at_bind).resolve()
        current = Path(self.root).resolve()
        if current != bound:
            raise RootInvariantError(
                f"repository root invariant violated: bound={bound} current={current}"
            )
        if not current.is_dir():
            raise RootInvariantError(f"repository root is not a directory: {current}")

    def to_resolver_context(self) -> ResolverRepositoryContext:
        self.assert_root_invariant()
        return ResolverRepositoryContext(
            remote=self.remote,
            repo_slug=self.repo_slug,
            project_id=self.project_id,
            destination_endpoint=self.destination_endpoint,
        )

    def to_envelope(self) -> dict[str, Any]:
        self.assert_root_invariant()
        return {
            "version": ENVELOPE_VERSION,
            "root": str(Path(self.root).resolve()),
            "projectId": self.project_id,
            "worktreeId": self.worktree_id,
            "planningAuthority": self.planning_authority,
            "credentialRefs": list(self.credential_refs),
            "memoryNamespace": self.memory_namespace,
            "policyOverrides": {key: value for key, value in self.policy_overrides},
            "runId": self.run_id,
            "remote": self.remote,
            "repoSlug": self.repo_slug,
            "destinationEndpoint": self.destination_endpoint,
        }

    def serialize_envelope(self) -> str:
        return json.dumps(self.to_envelope(), separators=(",", ":"), sort_keys=True)


def _default_destination_endpoint(provider: str) -> str:
    if provider == "gitlab":
        return "https://gitlab.com/api/v4/user"
    if provider == "bitbucket":
        return "https://api.bitbucket.org/2.0/user"
    return "https://api.github.com/user"


def _planning_authority(cfg: Mapping[str, Any]) -> str:
    planning = cfg.get("planning")
    if not isinstance(planning, dict):
        return "none"
    store = planning.get("store")
    if not isinstance(store, dict):
        return "none"
    backend = str(store.get("backend") or "").strip()
    provider = str(store.get("issuesProvider") or "").strip()
    if backend and provider:
        return f"{backend}:{provider}"
    return backend or provider or "none"


def _policy_overrides(cfg: Mapping[str, Any]) -> tuple[tuple[str, str], ...]:
    overrides: list[tuple[str, str]] = []
    orchestration = cfg.get("orchestration")
    if isinstance(orchestration, dict):
        plan_policy = orchestration.get("planPolicy")
        if isinstance(plan_policy, str) and plan_policy.strip():
            overrides.append(("orchestration.planPolicy", plan_policy.strip()))
    planning = cfg.get("planning")
    if isinstance(planning, dict):
        visibility = planning.get("visibilityTier")
        if isinstance(visibility, str) and visibility.strip():
            overrides.append(("planning.visibilityTier", visibility.strip()))
    return tuple(overrides)


def _worktree_id(root: Path) -> str:
    state_path = root / ".cursor" / "sw-worktree-state.json"
    if state_path.is_file():
        try:
            payload = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            for key in ("worktreeName", "name", "worktreeId"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return root.name or str(root.resolve())


def _credential_refs(root: Path) -> tuple[str, ...]:
    selector_path = Path.home() / ".config" / "shipwright" / "credential-selector.json"
    if not selector_path.is_file():
        return ()
    try:
        payload = json.loads(selector_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ()
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return ()
    refs = sorted(str(key).strip() for key in entries if str(key).strip())
    return tuple(refs)


def _git_common_dir(root: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    common = Path(raw)
    if not common.is_absolute():
        common = (root / common).resolve()
    return common


def from_root(
    root: Path | str,
    *,
    run_id: str | None = None,
    destination_endpoint: str | None = None,
    credential_refs: Sequence[str] | None = None,
) -> RepositoryContext:
    """Construct a repository context from a workspace root without module globals."""
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise RepositoryContextError(f"repository root is not a directory: {resolved}")

    cfg = load_workflow_config(resolved)
    host = cfg.get("host") if isinstance(cfg.get("host"), dict) else {}
    memory = cfg.get("memory") if isinstance(cfg.get("memory"), dict) else {}

    remote = git_remote_url(resolved, remote_name(cfg)) or ""
    slug = repo_slug_from_remote(remote)
    provider = str(host.get("provider") or "github").strip().lower()
    endpoint = destination_endpoint or _default_destination_endpoint(provider)

    project_id = str(memory.get("project") or slug or resolved.name).strip()
    memory_namespace = str(memory.get("project") or project_id).strip()
    effective_run_id = (run_id or os.environ.get("SW_RUN_ID") or os.environ.get("SW_DELIVER_RUN_ID") or "").strip()
    refs = tuple(credential_refs) if credential_refs is not None else _credential_refs(resolved)

    bound = str(resolved)
    return RepositoryContext(
        root=bound,
        project_id=project_id,
        worktree_id=_worktree_id(resolved),
        planning_authority=_planning_authority(cfg),
        credential_refs=refs,
        memory_namespace=memory_namespace,
        policy_overrides=_policy_overrides(cfg),
        run_id=effective_run_id or None,
        remote=remote,
        repo_slug=slug,
        destination_endpoint=endpoint,
        _root_at_bind=bound,
    )


def _reject_secret_envelope_fields(payload: Mapping[str, Any]) -> None:
    for key, value in payload.items():
        key_text = str(key)
        if key_text not in _ALLOWED_ENVELOPE_KEYS:
            if key_text in _BLOCKED_ENVELOPE_KEYS or _SECRET_KEY_RE.search(key_text):
                raise RepositoryContextError(f"envelope contains secret-bearing key: {key_text}")
        if isinstance(value, str) and _SECRET_VALUE_RE.search(value):
            raise RepositoryContextError("envelope contains secret-bearing value")
    refs = payload.get("credentialRefs")
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, str) or not item.strip():
                raise RepositoryContextError("credentialRefs must contain non-empty reference names")
            if _SECRET_VALUE_RE.search(item):
                raise RepositoryContextError("envelope contains secret-bearing credential reference")


def from_envelope(payload: Mapping[str, Any]) -> RepositoryContext:
    """Deserialize a non-secret context envelope."""
    if not isinstance(payload, Mapping):
        raise RepositoryContextError("envelope payload must be a mapping")
    _reject_secret_envelope_fields(payload)

    version = payload.get("version")
    if version != ENVELOPE_VERSION:
        raise RepositoryContextError(f"unsupported envelope version: {version!r}")

    root = str(payload.get("root") or "").strip()
    if not root:
        raise RepositoryContextError("envelope root is required")

    bound = str(Path(root).resolve())
    return RepositoryContext(
        root=bound,
        project_id=str(payload.get("projectId") or "").strip(),
        worktree_id=str(payload.get("worktreeId") or "").strip(),
        planning_authority=str(payload.get("planningAuthority") or "").strip(),
        credential_refs=tuple(str(item).strip() for item in payload.get("credentialRefs") or () if str(item).strip()),
        memory_namespace=str(payload.get("memoryNamespace") or "").strip(),
        policy_overrides=tuple(
            (str(key), str(value))
            for key, value in (payload.get("policyOverrides") or {}).items()
            if str(key).strip()
        ),
        run_id=(str(payload.get("runId")).strip() or None) if payload.get("runId") is not None else None,
        remote=str(payload.get("remote") or "").strip(),
        repo_slug=str(payload.get("repoSlug") or "").strip(),
        destination_endpoint=str(payload.get("destinationEndpoint") or "").strip(),
        _root_at_bind=bound,
    )


def parse_envelope(raw: str) -> RepositoryContext:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RepositoryContextError("envelope is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise RepositoryContextError("envelope JSON must be an object")
    return from_envelope(payload)


def envelope_from_env(env: Mapping[str, str] | None = None) -> RepositoryContext | None:
    source = env if env is not None else os.environ
    raw = str(source.get(CONTEXT_ENVELOPE_ENV) or "").strip()
    if not raw:
        return None
    return parse_envelope(raw)


def envelope_env_for_context(context: RepositoryContext) -> dict[str, str]:
    return {CONTEXT_ENVELOPE_ENV: context.serialize_envelope()}


def merge_forwarded_envelope(
    parent: Mapping[str, str],
    *,
    context: RepositoryContext | None = None,
) -> dict[str, str]:
    """Return parent env with a serialized non-secret envelope when available."""
    merged = dict(parent)
    if context is not None:
        merged.update(envelope_env_for_context(context))
        return merged
    existing = envelope_from_env(parent)
    if existing is not None:
        merged.update(envelope_env_for_context(existing))
    return merged
