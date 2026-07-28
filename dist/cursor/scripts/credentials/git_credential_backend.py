"""Hardened git-credential backend — pins selector helper, neutralizes repo config (PRD 080 phase 9 / R3)."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from credentials import failure_codes as fc
from credentials.child_env import build_hook_verify_child_env
from credentials.model import Principal, ResolutionState, Secret
from credentials.resolver import BackendResolveResult, RepositoryContext, register_backend_adapter
from credentials.selector_store import SelectorEntry, resolve_xdg_config_home

ALLOWED_GIT_CREDENTIAL_HELPERS: Final[frozenset[str]] = frozenset(
    {
        "cache",
        "store",
        "osxkeychain",
        "wincred",
        "manager",
        "manager-core",
        "libsecret",
    }
)

_GIT_CONFIG_INJECTION_PREFIXES: Final[tuple[str, ...]] = (
    "GIT_CONFIG",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_KEY_",
    "GIT_CONFIG_VALUE_",
    "GIT_CONFIG_PARAMETERS",
)

_CREDENTIAL_HELPER_RE = re.compile(
    r"^\s*(?:helper|credential\.helper)\s*=\s*(?P<value>.+?)\s*$",
    re.IGNORECASE,
)

GitCredentialRunner = Callable[..., subprocess.CompletedProcess[str]]


class GitCredentialBackendError(ValueError):
    """Fail-closed git-credential configuration error."""

    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(hint)


def _normalize_helper_token(raw: str) -> str:
    value = raw.strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1].strip()
    if value.startswith("'") and value.endswith("'"):
        value = value[1:-1].strip()
    return value


def validate_pinned_helper(helper: str | None) -> str:
    """Validate the selector-pinned helper and reject shell-form or off-allowlist values."""
    if helper is None or not str(helper).strip():
        raise GitCredentialBackendError(
            fc.UNAVAILABLE_BACKEND,
            "git_credential backend requires a pinned credential helper in the selector account field",
        )
    normalized = _normalize_helper_token(str(helper))
    if not normalized:
        raise GitCredentialBackendError(
            fc.UNAVAILABLE_BACKEND,
            "git_credential backend requires a pinned credential helper in the selector account field",
        )
    if normalized.startswith("!"):
        raise GitCredentialBackendError(
            fc.UNAVAILABLE_BACKEND,
            "shell-form credential helpers are refused",
        )
    if normalized not in ALLOWED_GIT_CREDENTIAL_HELPERS:
        raise GitCredentialBackendError(
            fc.UNAVAILABLE_BACKEND,
            "credential helper is outside the broker allowlist",
        )
    return normalized


def iter_credential_helpers_from_config(config_text: str) -> tuple[str, ...]:
    """Extract credential helper values from a git config document."""
    helpers: list[str] = []
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith(";"):
            continue
        match = _CREDENTIAL_HELPER_RE.match(stripped)
        if match:
            helpers.append(_normalize_helper_token(match.group("value")))
    return tuple(helpers)


def validate_repository_credential_config(config_text: str) -> None:
    """Reject repository-supplied credential helpers before any git invocation."""
    for helper in iter_credential_helpers_from_config(config_text):
        validate_pinned_helper(helper)


def broker_git_config_dir(
    *,
    ref: str,
    xdg_base: Path | None = None,
    broker_root: Path | None = None,
) -> Path:
    digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]
    if broker_root is not None:
        return broker_root / digest
    return resolve_xdg_config_home(xdg_base) / "shipwright" / "git-credential" / digest


def write_broker_git_config(path: Path, *, helper: str) -> Path:
    """Write a broker-controlled global git config that pins the helper and disables includes."""
    pinned = validate_pinned_helper(helper)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    content = (
        "[credential]\n"
        f"\thelper = {pinned}\n"
        "[include]\n"
        "\tpath =\n"
    )
    path.write_text(content, encoding="utf-8")
    os.chmod(path, 0o600)
    return path


def _strip_git_config_injection(env: Mapping[str, str]) -> dict[str, str]:
    sanitized: dict[str, str] = {}
    for key, value in env.items():
        upper = key.upper()
        if any(upper == prefix or upper.startswith(prefix) for prefix in _GIT_CONFIG_INJECTION_PREFIXES):
            continue
        sanitized[key] = value
    return sanitized


def build_git_credential_env(
    parent: Mapping[str, str] | None = None,
    *,
    broker_global_config: Path,
    declared_context_keys: Sequence[str] = (),
) -> dict[str, str]:
    """Build a sanitized child environment for git credential resolution."""
    source = parent if parent is not None else os.environ
    env = build_hook_verify_child_env(
        _strip_git_config_injection(source),
        declared_context_keys=declared_context_keys,
    )
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = str(broker_global_config.resolve())
    return env


def _credential_fill_input(*, protocol: str, host: str) -> str:
    return f"protocol={protocol}\nhost={host}\n\n"


def _parse_credential_fill_output(stdout: str) -> tuple[str, Secret] | None:
    login_name: str | None = None
    secret_value: str | None = None
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "username":
            login_name = value.strip()
        elif key == "password":
            secret_value = value.strip()
    if not secret_value:
        return None
    token_value = secret_value if secret_value else (login_name or "")
    if not token_value:
        return None
    profile = login_name or "git-credential"
    return profile, Secret(token_value)


@dataclass(frozen=True, slots=True)
class GitCredentialInvocation:
    helper: str
    host: str
    protocol: str
    env: Mapping[str, str]
    cwd: Path


def default_git_credential_runner(invocation: GitCredentialInvocation) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "credential", "fill"],
        input=_credential_fill_input(protocol=invocation.protocol, host=invocation.host),
        env=dict(invocation.env),
        cwd=invocation.cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class GitCredentialBackendAdapter:
    """Resolve credentials via a pinned, allowlisted git credential helper."""

    def __init__(
        self,
        *,
        runner: GitCredentialRunner | None = None,
        xdg_base: Path | None = None,
        broker_root: Path | None = None,
        work_dir: Path | None = None,
    ) -> None:
        self._runner = runner
        self._xdg_base = xdg_base
        self._broker_root = broker_root
        self._work_dir = work_dir

    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = purpose
        try:
            helper = validate_pinned_helper(entry.account)
            host = (entry.hostname or "").strip().lower()
            if not host:
                host = _host_from_remote(context.remote)
            if not host:
                raise GitCredentialBackendError(
                    fc.INSUFFICIENT_SCOPE,
                    "git_credential backend requires a hostname in the selector entry or repository remote",
                )
            config_path = broker_git_config_dir(
                ref=entry.ref,
                xdg_base=self._xdg_base,
                broker_root=self._broker_root,
            )
            broker_config = write_broker_git_config(config_path / "config", helper=helper)
            env = build_git_credential_env(broker_global_config=broker_config)
            cwd = self._work_dir or Path.cwd()
            if self._runner is not None:
                completed = self._runner(
                    GitCredentialInvocation(
                        helper=helper,
                        host=host,
                        protocol="https",
                        env=env,
                        cwd=cwd,
                    )
                )
            else:
                completed = default_git_credential_runner(
                    GitCredentialInvocation(
                        helper=helper,
                        host=host,
                        protocol="https",
                        env=env,
                        cwd=cwd,
                    )
                )
        except GitCredentialBackendError as exc:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=exc.code,
                backend=entry.backend,
            )

        if completed.returncode != 0:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.INSUFFICIENT_ACCESS,
                backend=entry.backend,
            )

        parsed = _parse_credential_fill_output(completed.stdout)
        if parsed is None:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.INSUFFICIENT_ACCESS,
                backend=entry.backend,
            )

        profile, token = parsed
        principal = Principal(profile=profile, account=entry.account)
        return BackendResolveResult(
            state=ResolutionState.RESOLVED,
            token=token,
            principal=principal,
            backend=entry.backend,
        )


def _host_from_remote(remote: str) -> str:
    value = remote.strip()
    if not value:
        return ""
    if value.startswith("git@"):
        host_part = value.split(":", 1)[0]
        return host_part.removeprefix("git@").strip().lower()
    if "://" in value:
        from urllib.parse import urlparse

        return (urlparse(value).hostname or "").lower()
    return ""


def register_git_credential_backend(adapter: GitCredentialBackendAdapter | None = None) -> None:
    register_backend_adapter("git_credential", adapter or GitCredentialBackendAdapter())


register_git_credential_backend()
