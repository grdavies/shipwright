"""Committed config surface for projectId + credentialRef (PRD 080 phase 17 / R1).

Validates top-level project id, resolves host / planning-store / memory credential
references with credentialRef-wins precedence, and applies the one-release
tokenEnv compatibility alias (warn on combination during deprecation; error after
cutover). Alias notices emit exactly once per resolve invocation.
"""

from __future__ import annotations

import importlib
import re
import warnings
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from credentials.pairing_store import load_pairing_store

# Documented slug pattern — keep in sync with .sw/config.schema.json projectId.
PROJECT_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
PROJECT_ID_PATTERN_DOC = "^[a-z][a-z0-9-]*$"

ALIAS_NOTICE = (
    "tokenEnv is a one-release compatibility alias; set credentialRef and remove "
    "tokenEnv (credentialRef wins when both are set)"
)

COMBINATION_WARNING = (
    "both credentialRef and tokenEnv are set; credentialRef wins — remove tokenEnv "
    "before the deprecation cutover"
)

COMBINATION_ERROR = (
    "both credentialRef and tokenEnv are set after deprecation cutover; "
    "remove tokenEnv and keep credentialRef only"
)

# Named migration targets that must be deleted at cutover (080-A4).
IMPLICIT_DEFAULT_TABLE_TARGETS: tuple[str, ...] = (
    "host_lib.DEFAULT_TOKEN_ENV",
    "planning_store.DEFAULT_ISSUES_TOKEN_ENV",
    "closeout_ci.hardcoded_token_env_defaults",
)

SURFACES: tuple[str, ...] = ("host", "planning", "memory")


class DeprecationPhase(str, Enum):
    """Deprecation release accepts aliases with warnings; cutover errors and drops tables."""

    DEPRECATION = "deprecation"
    CUTOVER = "cutover"


class ConfigSurfaceError(Exception):
    """Fail-closed config surface error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


class CutoverError(ConfigSurfaceError):
    """Raised when cutover invariants are violated."""


@dataclass(frozen=True, slots=True)
class ResolvedCredentialSurface:
    """Resolved credential binding for one config surface."""

    surface: str
    credential_ref: str | None
    token_env: str | None
    source: str  # credentialRef | tokenEnv-alias | absent


@dataclass(frozen=True, slots=True)
class ConfigSurfaceResult:
    """Full committed-config resolution for one repository."""

    project_id: str
    host: ResolvedCredentialSurface
    planning: ResolvedCredentialSurface
    memory: ResolvedCredentialSurface
    notices: tuple[str, ...]
    warnings: tuple[str, ...]


def validate_project_id(project_id: str | None) -> str:
    """Validate a top-level project id against the documented slug pattern."""
    if project_id is None or not str(project_id).strip():
        raise ConfigSurfaceError(
            "project-id-absent",
            "top-level projectId is required",
        )
    value = str(project_id).strip()
    if not PROJECT_ID_PATTERN.fullmatch(value):
        raise ConfigSurfaceError(
            "project-id-pattern",
            f"projectId {value!r} must match {PROJECT_ID_PATTERN_DOC}",
        )
    return value


def _section(cfg: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    node: Any = cfg
    for key in keys:
        if not isinstance(node, Mapping):
            return {}
        node = node.get(key)
    return node if isinstance(node, Mapping) else {}


def _optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_surface(
    surface: str,
    *,
    credential_ref: str | None,
    token_env: str | None,
    deprecation_phase: DeprecationPhase,
    notices: list[str],
    warn_messages: list[str],
    alias_notice_emitted: list[bool],
) -> ResolvedCredentialSurface:
    has_ref = credential_ref is not None
    has_token = token_env is not None

    if has_ref and has_token:
        if deprecation_phase is DeprecationPhase.CUTOVER:
            raise ConfigSurfaceError("tokenenv-cutover-combination", COMBINATION_ERROR)
        warn_messages.append(f"{surface}: {COMBINATION_WARNING}")
        warnings.warn(f"{surface}: {COMBINATION_WARNING}", DeprecationWarning, stacklevel=3)
        return ResolvedCredentialSurface(
            surface=surface,
            credential_ref=credential_ref,
            token_env=token_env,
            source="credentialRef",
        )

    if has_ref:
        return ResolvedCredentialSurface(
            surface=surface,
            credential_ref=credential_ref,
            token_env=None,
            source="credentialRef",
        )

    if has_token:
        if deprecation_phase is DeprecationPhase.CUTOVER:
            raise ConfigSurfaceError(
                "tokenenv-cutover-alias",
                f"{surface}: tokenEnv alias removed at cutover; set credentialRef",
            )
        if not alias_notice_emitted[0]:
            notices.append(ALIAS_NOTICE)
            alias_notice_emitted[0] = True
        return ResolvedCredentialSurface(
            surface=surface,
            credential_ref=None,
            token_env=token_env,
            source="tokenEnv-alias",
        )

    return ResolvedCredentialSurface(
        surface=surface,
        credential_ref=None,
        token_env=None,
        source="absent",
    )


def _extract_surface_values(cfg: Mapping[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    host = _section(cfg, "host")
    planning_issues = _section(cfg, "planning", "store", "issues")
    memory = _section(cfg, "memory")
    return {
        "host": (_optional_str(host.get("credentialRef")), _optional_str(host.get("tokenEnv"))),
        "planning": (
            _optional_str(planning_issues.get("credentialRef")),
            _optional_str(planning_issues.get("tokenEnv")),
        ),
        "memory": (_optional_str(memory.get("credentialRef")), _optional_str(memory.get("tokenEnv"))),
    }


def detect_project_id_pairing_conflict(
    project_id: str,
    remote: str,
    *,
    pairing_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
) -> None:
    """Block resolution when an inherited project id is paired to a different remote."""
    if not remote.strip():
        return
    records = load_pairing_store(
        path=pairing_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity or pairing_path is not None,
    )
    conflicts = [
        record
        for record in records.values()
        if record.project_id == project_id and record.remote != remote.strip()
    ]
    if not conflicts:
        return
    remotes = sorted({record.remote for record in conflicts})
    raise ConfigSurfaceError(
        "project-id-pairing-conflict",
        (
            f"projectId {project_id!r} is already paired to remote(s) {remotes}; "
            "re-pair before resolving this repository"
        ),
    )


def resolve_config_surface(
    cfg: Mapping[str, Any],
    *,
    remote: str | None = None,
    pairing_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
    deprecation_phase: DeprecationPhase | str = DeprecationPhase.DEPRECATION,
) -> ConfigSurfaceResult:
    """Resolve project id + credential surfaces for one config document."""
    phase = (
        deprecation_phase
        if isinstance(deprecation_phase, DeprecationPhase)
        else DeprecationPhase(str(deprecation_phase))
    )
    project_id = validate_project_id(_optional_str(cfg.get("projectId")))
    if remote is not None:
        detect_project_id_pairing_conflict(
            project_id,
            remote,
            pairing_path=pairing_path,
            xdg_base=xdg_base,
            skip_integrity=skip_integrity,
        )

    notices: list[str] = []
    warn_messages: list[str] = []
    alias_notice_emitted = [False]
    values = _extract_surface_values(cfg)
    resolved: dict[str, ResolvedCredentialSurface] = {}
    for surface in SURFACES:
        cred_ref, token_env = values[surface]
        resolved[surface] = _resolve_surface(
            surface,
            credential_ref=cred_ref,
            token_env=token_env,
            deprecation_phase=phase,
            notices=notices,
            warn_messages=warn_messages,
            alias_notice_emitted=alias_notice_emitted,
        )

    return ConfigSurfaceResult(
        project_id=project_id,
        host=resolved["host"],
        planning=resolved["planning"],
        memory=resolved["memory"],
        notices=tuple(notices),
        warnings=tuple(warn_messages),
    )


def _module_has_attr(module_name: str, attr: str) -> bool:
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return False
    return hasattr(module, attr)


def present_implicit_default_tables() -> tuple[str, ...]:
    """Return which named implicit-default migration targets are still present."""
    present: list[str] = []
    if _module_has_attr("host_lib", "DEFAULT_TOKEN_ENV"):
        present.append("host_lib.DEFAULT_TOKEN_ENV")
    if _module_has_attr("planning_store", "DEFAULT_ISSUES_TOKEN_ENV"):
        present.append("planning_store.DEFAULT_ISSUES_TOKEN_ENV")
    # closeout_ci uses inline hardcoded defaults (no named table yet) — present until cutover removes them.
    try:
        closeout = importlib.import_module("closeout_ci")
    except ImportError:
        closeout = None
    if closeout is not None:
        source = Path(getattr(closeout, "__file__", "") or "")
        text = source.read_text(encoding="utf-8") if source.is_file() else ""
        if "SW_PLANNING_ISSUES_TOKEN" in text or '"GITHUB_TOKEN"' in text or "'GITHUB_TOKEN'" in text:
            present.append("closeout_ci.hardcoded_token_env_defaults")
    return tuple(target for target in IMPLICIT_DEFAULT_TABLE_TARGETS if target in present)


def assert_implicit_default_tables_absent_at_cutover(
    *,
    deprecation_phase: DeprecationPhase | str = DeprecationPhase.CUTOVER,
) -> None:
    """At cutover, the three implicit default tables must be deleted (080-A4)."""
    phase = (
        deprecation_phase
        if isinstance(deprecation_phase, DeprecationPhase)
        else DeprecationPhase(str(deprecation_phase))
    )
    if phase is not DeprecationPhase.CUTOVER:
        return
    remaining = present_implicit_default_tables()
    if remaining:
        raise CutoverError(
            "implicit-default-tables-present",
            f"cutover requires deletion of: {', '.join(remaining)}",
        )
