"""GitHub CLI backend with per-reference GH_CONFIG_DIR isolation (PRD 080 phase 8 / R5, R6)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from credentials import failure_codes as fc
from credentials.child_env import (
    GH_CONFIG_DIR_ENV,
    GH_HOST_ENV,
    build_hook_verify_child_env,
    build_host_cli_child_env,
)
from credentials.model import Principal, ResolutionState, Secret
from credentials.resolver import BackendResolveResult, RepositoryContext, register_backend_adapter
from credentials.selector_store import SelectorEntry, resolve_xdg_config_home

GH_PROMPT_DISABLED_ENV: Final[str] = "GH_PROMPT_DISABLED"
DEFAULT_CREDENTIAL_ENV_NAME: Final[str] = "GH_TOKEN"
_SCOPE_LINE_RE = re.compile(r"Token scopes:\s*'?(?P<scopes>[^'\n]+)'?", re.IGNORECASE)

GithubCliRunner = Callable[["GithubCliInvocation"], subprocess.CompletedProcess[str]]


class GithubCliBackendError(ValueError):
    """Fail-closed GitHub CLI backend configuration or invocation error."""

    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(hint)


@dataclass(frozen=True, slots=True)
class ScopeProbeResult:
    """Outcome of a non-secret scope probe against the isolated gh configuration."""

    granted_scopes: tuple[str, ...]
    required_scopes: tuple[str, ...]
    shortfall: tuple[str, ...]

    @property
    def sufficient(self) -> bool:
        return not self.shortfall


@dataclass(frozen=True, slots=True)
class EnforceabilityStatement:
    """Published statement describing how github_cli isolation is enforced."""

    mechanism: str
    isolation_key: str
    scope_probe_command: str
    prohibits_account_switch: bool
    credential_env_name: str


GITHUB_CLI_ENFORCEABILITY: Final[EnforceabilityStatement] = EnforceabilityStatement(
    mechanism="one broker-managed GH_CONFIG_DIR per credential reference",
    isolation_key=GH_CONFIG_DIR_ENV,
    scope_probe_command="gh auth status",
    prohibits_account_switch=True,
    credential_env_name=DEFAULT_CREDENTIAL_ENV_NAME,
)


@dataclass(frozen=True, slots=True)
class GithubCliInvocation:
    argv: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path


def enforceability_statement() -> EnforceabilityStatement:
    return GITHUB_CLI_ENFORCEABILITY


def broker_gh_config_dir(
    *,
    ref: str,
    xdg_base: Path | None = None,
    broker_root: Path | None = None,
) -> Path:
    """Return a broker-managed configuration directory for one credential reference."""
    digest = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]
    if broker_root is not None:
        return broker_root / digest
    return resolve_xdg_config_home(xdg_base) / "shipwright" / "github-cli" / digest


def resolve_credential_env_name(entry: SelectorEntry) -> str:
    """Return the single env-backend variable re-supplied into the sanitized child environment."""
    _ = entry
    return DEFAULT_CREDENTIAL_ENV_NAME


def required_scopes_for_purpose(purpose: str) -> tuple[str, ...]:
    normalized = purpose.strip().lower()
    if normalized in {"public", "no-auth", "explicitly-no-auth"}:
        return ()
    if normalized in {"read", "probe", "status"}:
        return ("read:user",)
    return ("repo",)


def parse_scopes_from_auth_status(stdout: str) -> tuple[str, ...]:
    for line in stdout.splitlines():
        match = _SCOPE_LINE_RE.search(line)
        if not match:
            continue
        raw = match.group("scopes").strip()
        if not raw:
            return ()
        return tuple(scope.strip() for scope in raw.split(",") if scope.strip())
    return ()


def probe_scopes(
    granted: Sequence[str],
    required: Sequence[str],
) -> ScopeProbeResult:
    granted_set = {scope.strip() for scope in granted if scope.strip()}
    required_tuple = tuple(scope.strip() for scope in required if scope.strip())
    shortfall = tuple(scope for scope in required_tuple if scope not in granted_set)
    return ScopeProbeResult(
        granted_scopes=tuple(sorted(granted_set)),
        required_scopes=required_tuple,
        shortfall=shortfall,
    )


def locate_gh_executable() -> str | None:
    return shutil.which("gh")


def _gh_hostname(entry: SelectorEntry) -> str:
    host = (entry.hostname or "").strip().lower()
    return host or "github.com"


def _prepare_config_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def build_github_cli_probe_env(
    parent: Mapping[str, str] | None,
    *,
    gh_host: str,
    gh_config_dir: str,
    declared_context_keys: Sequence[str] = (),
) -> dict[str, str]:
    """Build a sanitized child environment for non-interactive gh auth probes."""
    env = build_hook_verify_child_env(
        parent,
        declared_context_keys=declared_context_keys,
    )
    env[GH_HOST_ENV] = gh_host
    env[GH_CONFIG_DIR_ENV] = gh_config_dir
    env[GH_PROMPT_DISABLED_ENV] = "1"
    return env


def build_github_cli_child_env(
    parent: Mapping[str, str] | None,
    *,
    entry: SelectorEntry,
    gh_host: str,
    gh_config_dir: str,
    credential_env_value: str,
    declared_context_keys: Sequence[str] = (),
) -> dict[str, str]:
    """Re-supply exactly the resolved env-backend variable into the sanitized child environment."""
    credential_env_name = resolve_credential_env_name(entry)
    env = build_host_cli_child_env(
        parent,
        declared_context_keys=declared_context_keys,
        credential_env_name=credential_env_name,
        credential_env_value=credential_env_value,
        gh_host=gh_host,
        gh_config_dir=gh_config_dir,
    )
    env[GH_PROMPT_DISABLED_ENV] = "1"
    return env


def _auth_status_argv(host: str) -> tuple[str, ...]:
    if host == "github.com":
        return ("gh", "auth", "status")
    return ("gh", "auth", "status", "--hostname", host)


def default_github_cli_runner(invocation: GithubCliInvocation) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(invocation.argv),
        env=dict(invocation.env),
        cwd=invocation.cwd,
        capture_output=True,
        text=True,
        check=False,
    )


class GithubCliBackendAdapter:
    """Resolve credentials via an isolated GitHub CLI configuration directory."""

    def __init__(
        self,
        *,
        runner: GithubCliRunner | None = None,
        gh_executable: str | None = None,
        xdg_base: Path | None = None,
        broker_root: Path | None = None,
        work_dir: Path | None = None,
        declared_context_keys: Sequence[str] = (),
    ) -> None:
        self._runner = runner
        self._gh_executable = gh_executable
        self._xdg_base = xdg_base
        self._broker_root = broker_root
        self._work_dir = work_dir
        self._declared_context_keys = tuple(declared_context_keys)

    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = context
        gh_path = self._gh_executable if self._gh_executable is not None else locate_gh_executable()
        if not gh_path:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=fc.UNAVAILABLE_BACKEND,
                backend=entry.backend,
            )

        host = _gh_hostname(entry)
        config_dir = _prepare_config_dir(
            broker_gh_config_dir(
                ref=entry.ref,
                xdg_base=self._xdg_base,
                broker_root=self._broker_root,
            )
        )
        probe_env = build_github_cli_probe_env(
            None,
            gh_host=host,
            gh_config_dir=str(config_dir.resolve()),
            declared_context_keys=self._declared_context_keys,
        )
        cwd = self._work_dir or Path.cwd()
        runner = self._runner or default_github_cli_runner

        try:
            token_completed = runner(
                GithubCliInvocation(
                    argv=(gh_path, "auth", "token"),
                    env=probe_env,
                    cwd=cwd,
                )
            )
            if token_completed.returncode != 0:
                raise GithubCliBackendError(
                    fc.INSUFFICIENT_ACCESS,
                    "gh auth token failed for the broker-managed configuration directory",
                )
            token_value = token_completed.stdout.strip()
            if not token_value:
                raise GithubCliBackendError(
                    fc.INSUFFICIENT_ACCESS,
                    "gh auth token returned no credential for the broker-managed configuration directory",
                )

            status_completed = runner(
                GithubCliInvocation(
                    argv=_auth_status_argv(host),
                    env=probe_env,
                    cwd=cwd,
                )
            )
            if status_completed.returncode != 0:
                raise GithubCliBackendError(
                    fc.INSUFFICIENT_ACCESS,
                    "gh auth status failed for the broker-managed configuration directory",
                )

            scope_result = probe_scopes(
                parse_scopes_from_auth_status(status_completed.stdout),
                required_scopes_for_purpose(purpose),
            )
            if not scope_result.sufficient:
                return BackendResolveResult(
                    state=ResolutionState.UNRESOLVED,
                    failure_code=fc.INSUFFICIENT_SCOPE,
                    backend=entry.backend,
                )

            child_env = build_github_cli_child_env(
                None,
                entry=entry,
                gh_host=host,
                gh_config_dir=str(config_dir.resolve()),
                credential_env_value=token_value,
                declared_context_keys=self._declared_context_keys,
            )
            _ = child_env
        except GithubCliBackendError as exc:
            return BackendResolveResult(
                state=ResolutionState.UNRESOLVED,
                failure_code=exc.code,
                backend=entry.backend,
            )

        principal = Principal(
            profile=entry.account or entry.ref,
            account=entry.account,
        )
        return BackendResolveResult(
            state=ResolutionState.RESOLVED,
            token=Secret(token_value),
            principal=principal,
            backend=entry.backend,
        )


def register_github_cli_backend(adapter: GithubCliBackendAdapter | None = None) -> None:
    register_backend_adapter("github_cli", adapter or GithubCliBackendAdapter())


register_github_cli_backend()
