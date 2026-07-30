"""Repository CI env-backend selector declaration and preflight (PRD 080 phase 10 / R6)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping

from credentials import failure_codes as fc
from credentials.selector_store import (
    SelectorDocument,
    SelectorEntry,
    SelectorStoreError,
    default_selector_path,
    load_selector_store,
)

CI_SELECTOR_RELATIVE: Final[Path] = Path(".sw") / "credential-ci-selector.json"
GITHUB_ACTIONS_ENV: Final[str] = "GITHUB_ACTIONS"
CI_SELECTOR_ABSENT_CODE: Final[str] = "ci-selector-absent"
CI_SELECTOR_INVALID_CODE: Final[str] = "ci-selector-invalid"
MISSING_CI_DECLARATION_REMEDIATION: Final[str] = (
    "declare the env backend in repository CI configuration at "
    f"{CI_SELECTOR_RELATIVE.as_posix()} or the machine-local selector file"
)

# Standard CI token env vars per provider — used as a fallback when workflow config
# has no explicit tokenEnv, e.g. when loading from a bare tmp dir in tests or CI.
_PROVIDER_DEFAULT_TOKEN_ENVS: Final[dict[str, str]] = {
    "github": "GITHUB_TOKEN",
    "gitlab": "GITLAB_TOKEN",
    "bitbucket": "BITBUCKET_TOKEN",
}


@dataclass(frozen=True, slots=True)
class AmbientTokenFinding:
    """Non-secret report when Actions exposes a token without an explicit declaration."""

    detected: bool
    token_env: str
    remediation: str


@dataclass(frozen=True, slots=True)
class DeprecationReleasePreflightResult:
    verdict: str
    code: str | None
    remediation: str | None
    local_declared: bool
    ci_declared: bool
    ambient_finding: AmbientTokenFinding | None


def is_github_actions(environ: Mapping[str, str] | None = None) -> bool:
    source = environ if environ is not None else os.environ
    return source.get(GITHUB_ACTIONS_ENV, "").strip().lower() in {"1", "true", "yes"}


def ci_selector_path(root: Path | str) -> Path:
    return Path(root).expanduser().resolve() / CI_SELECTOR_RELATIVE


def load_ci_selector_store(*, root: Path | str) -> SelectorDocument:
    """Load the repository-declared CI selector without machine-local integrity checks."""
    path = ci_selector_path(root)
    if not path.is_file():
        raise SelectorStoreError(
            CI_SELECTOR_ABSENT_CODE,
            MISSING_CI_DECLARATION_REMEDIATION,
        )
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SelectorStoreError(
            CI_SELECTOR_INVALID_CODE,
            f"{CI_SELECTOR_RELATIVE.as_posix()} must be valid JSON",
        ) from exc
    return load_selector_store(path=path, skip_integrity=True)


def _environment_entries(document: SelectorDocument) -> dict[str, SelectorEntry]:
    return {
        ref: entry
        for ref, entry in document.entries.items()
        if entry.backend == "environment"
    }


def try_load_local_selector(
    *,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> SelectorDocument | None:
    path = selector_path or default_selector_path(xdg_base=xdg_base)
    try:
        return load_selector_store(path=path, xdg_base=xdg_base, skip_integrity=True)
    except SelectorStoreError as exc:
        if exc.code == "selector-absent":
            return None
        raise


def try_load_ci_selector(*, root: Path | str) -> SelectorDocument | None:
    try:
        return load_ci_selector_store(root=root)
    except SelectorStoreError as exc:
        if exc.code == CI_SELECTOR_ABSENT_CODE:
            return None
        raise


def is_environment_backend_declared(
    ref: str,
    *,
    root: Path | str,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> bool:
    """Return True when the reference is explicitly declared for the environment backend."""
    normalized = ref.strip()
    if not normalized:
        return False

    local = try_load_local_selector(selector_path=selector_path, xdg_base=xdg_base)
    if local is not None and normalized in _environment_entries(local):
        return True

    ci = try_load_ci_selector(root=root)
    if ci is not None and normalized in _environment_entries(ci):
        return True
    return False


def resolve_presence_env_name(entry: SelectorEntry, *, root: Path | str) -> str:
    """Return the host token env var used for presence checks and env-backend reads.

    Prefers the explicit ``tokenEnv`` from workflow config; falls back to the
    standard CI env var for the declared provider when no explicit value is set.
    """
    from host_lib import host_section, load_workflow_config, resolve_token_env

    cfg = load_workflow_config(Path(root))
    host = host_section(cfg)
    configured = resolve_token_env(host, entry.provider)
    if configured:
        return configured
    return _PROVIDER_DEFAULT_TOKEN_ENVS.get(entry.provider.strip().lower(), "")


def detect_ambient_token_without_declaration(
    *,
    root: Path | str,
    token_env: str,
    environ: Mapping[str, str] | None = None,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> AmbientTokenFinding:
    """Detect an ambient CI token when no explicit env-backend declaration exists."""
    source = environ if environ is not None else os.environ
    token_value = source.get(token_env, "").strip()
    if not token_value:
        return AmbientTokenFinding(
            detected=False,
            token_env=token_env,
            remediation=MISSING_CI_DECLARATION_REMEDIATION,
        )
    if not is_github_actions(source):
        return AmbientTokenFinding(
            detected=False,
            token_env=token_env,
            remediation=MISSING_CI_DECLARATION_REMEDIATION,
        )

    local = try_load_local_selector(selector_path=selector_path, xdg_base=xdg_base)
    ci = try_load_ci_selector(root=root)
    local_env = _environment_entries(local) if local is not None else {}
    ci_env = _environment_entries(ci) if ci is not None else {}
    if local_env or ci_env:
        return AmbientTokenFinding(
            detected=False,
            token_env=token_env,
            remediation=MISSING_CI_DECLARATION_REMEDIATION,
        )

    return AmbientTokenFinding(
        detected=True,
        token_env=token_env,
        remediation=MISSING_CI_DECLARATION_REMEDIATION,
    )


def deprecation_release_preflight(
    *,
    root: Path | str,
    token_env: str,
    environ: Mapping[str, str] | None = None,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> DeprecationReleasePreflightResult:
    """Fail closed when neither local nor CI declarations exist for the env backend."""
    source = environ if environ is not None else os.environ
    local = try_load_local_selector(selector_path=selector_path, xdg_base=xdg_base)
    ci = try_load_ci_selector(root=root)
    local_env = _environment_entries(local) if local is not None else {}
    ci_env = _environment_entries(ci) if ci is not None else {}
    local_declared = bool(local_env)
    ci_declared = bool(ci_env)

    ambient = detect_ambient_token_without_declaration(
        root=root,
        token_env=token_env,
        environ=source,
        selector_path=selector_path,
        xdg_base=xdg_base,
    )

    if local_declared or ci_declared:
        return DeprecationReleasePreflightResult(
            verdict="pass",
            code=None,
            remediation=None,
            local_declared=local_declared,
            ci_declared=ci_declared,
            ambient_finding=ambient if ambient.detected else None,
        )

    remediation = fc.failure_detail(fc.MISSING_CI_DECLARATION).hint
    if ambient.detected:
        remediation = ambient.remediation
    return DeprecationReleasePreflightResult(
        verdict="fail",
        code=fc.MISSING_CI_DECLARATION,
        remediation=remediation,
        local_declared=False,
        ci_declared=False,
        ambient_finding=ambient if ambient.detected else None,
    )
