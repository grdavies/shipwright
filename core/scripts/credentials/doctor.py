"""Identity-aware credential doctor (PRD 080 phase 22 / R7)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Final, Mapping

from credentials import failure_codes as fc
from credentials.ci_declaration import (
    CI_SELECTOR_RELATIVE,
    deprecation_release_preflight,
    is_environment_backend_declared,
    is_github_actions,
    try_load_ci_selector,
    try_load_local_selector,
)
from credentials.config_surface import (
    ALIAS_NOTICE,
    DeprecationPhase,
    ResolvedCredentialSurface,
    ConfigSurfaceError,
    resolve_config_surface,
)
from credentials.environment_backend import EnvironmentBackendAdapter
from credentials.model import CredentialRef, Principal, ResolutionState
from credentials.pairing_store import check_pairing, default_pairing_path
from credentials.resolver import RepositoryContext, register_backend_adapter, resolve_lookup
from credentials.selector_store import (
    SelectorDocument,
    SelectorEntry,
    SelectorStoreError,
    default_selector_path,
    load_selector_store,
)

RESOLUTION_JOURNAL_FILENAME: Final[str] = "credential-resolution.journal.jsonl"
RESOLUTION_JOURNAL_RELATIVE: Final[Path] = Path("shipwright") / RESOLUTION_JOURNAL_FILENAME

LOCAL_SCOPE: Final[str] = "local"
CI_SCOPE: Final[str] = "ci"

CREDENTIAL_DOCTOR_CLI: Final[str] = "python3 scripts/credentials-doctor.py"


class LegacyClassification(str, Enum):
    READY = "ready"
    NEEDS_LOCAL_SELECTOR = "needs-local-selector"
    NEEDS_CI_DECLARATION = "needs-ci-declaration"


@dataclass(frozen=True, slots=True)
class Remediation:
    scope: str
    command: str


@dataclass(frozen=True, slots=True)
class DoctorFailure:
    code: str
    remediation: Remediation


@dataclass(frozen=True, slots=True)
class SurfaceDiagnosis:
    surface: str
    repository: str
    project_id: str
    credential_ref: str | None
    resolved_principal: dict[str, str | None] | None
    scope_binding: dict[str, tuple[str, ...]] | None
    pairing: dict[str, Any]
    repository_access: str
    required_operation_verdict: str
    failure: DoctorFailure | None = None
    notices: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceListing:
    ref: str
    backend: str
    scopes: dict[str, tuple[str, ...]]
    principal: dict[str, str | None] | None
    last_successful_resolution: str | None


def default_resolution_journal_path(*, xdg_base: Path | None = None) -> Path:
    from credentials.selector_store import resolve_xdg_config_home

    return resolve_xdg_config_home(xdg_base) / RESOLUTION_JOURNAL_RELATIVE


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def remediation_command(*, scope: str, code: str, root: Path | str) -> str:
    root_path = Path(root).resolve()
    return (
        f"{CREDENTIAL_DOCTOR_CLI} remediate --scope {scope} --code {code} "
        f"--root {root_path}"
    )


def remediation_for_code(code: str, *, root: Path | str) -> Remediation:
    """Map a stable failure code to exactly one remediation command."""
    ci_codes = frozenset(
        {
            fc.MISSING_CI_DECLARATION,
        }
    )
    scope = CI_SCOPE if code in ci_codes else LOCAL_SCOPE
    return Remediation(scope=scope, command=remediation_command(scope=scope, code=code, root=root))


def _principal_public(principal: Principal | None) -> dict[str, str | None] | None:
    if principal is None:
        return None
    return {"profile": principal.profile, "account": principal.account}


def _notices_for_surface(
    surface_binding: ResolvedCredentialSurface,
    config_notices: tuple[str, ...],
) -> tuple[str, ...]:
    if surface_binding.source == "tokenEnv-alias" and config_notices:
        return config_notices
    return ()


def _scope_binding(entry: SelectorEntry | None) -> dict[str, tuple[str, ...]] | None:
    if entry is None:
        return None
    return {
        "allowedRepos": entry.allowed_repos,
        "allowedProjectIds": entry.allowed_project_ids,
        "allowedEndpoints": entry.allowed_endpoints,
    }


def _pairing_report(
    ref: str,
    context: RepositoryContext,
    *,
    pairing_path: Path | None,
    xdg_base: Path | None,
    skip_integrity: bool,
) -> dict[str, Any]:
    if not ref.strip():
        return {"verdict": "absent", "approved": False}
    result = check_pairing(
        ref,
        context.project_id,
        context.remote,
        path=pairing_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
    )
    return {
        "verdict": result.verdict.value,
        "approved": result.verdict.value == "allowed",
        "code": result.code,
    }


def load_resolution_journal(
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
) -> list[dict[str, str]]:
    journal_path = path or default_resolution_journal_path(xdg_base=xdg_base)
    if not journal_path.is_file():
        return []
    entries: list[dict[str, str]] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(raw, dict):
            entries.append(
                {
                    "ref": str(raw.get("ref", "")).strip(),
                    "recordedAt": str(raw.get("recordedAt", "")).strip(),
                    "profile": str(raw.get("profile", "")).strip(),
                    "account": str(raw.get("account", "")).strip(),
                }
            )
    return entries


def record_successful_resolution(
    ref: str,
    principal: Principal | None,
    *,
    path: Path | None = None,
    xdg_base: Path | None = None,
) -> str:
    journal_path = path or default_resolution_journal_path(xdg_base=xdg_base)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    recorded_at = _utc_now()
    payload = {
        "ref": ref.strip(),
        "recordedAt": recorded_at,
        "profile": principal.profile if principal else "",
        "account": principal.account or "" if principal else "",
    }
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    return recorded_at


def last_successful_resolution(
    ref: str,
    *,
    journal: list[dict[str, str]] | None = None,
    path: Path | None = None,
    xdg_base: Path | None = None,
) -> str | None:
    entries = journal if journal is not None else load_resolution_journal(path=path, xdg_base=xdg_base)
    normalized = ref.strip()
    for item in reversed(entries):
        if item.get("ref") == normalized and item.get("recordedAt"):
            return item["recordedAt"]
    return None


def list_known_references(
    *,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
    journal: list[dict[str, str]] | None = None,
) -> list[ReferenceListing]:
    try:
        document = load_selector_store(
            path=selector_path,
            xdg_base=xdg_base,
            skip_integrity=skip_integrity,
        )
    except SelectorStoreError:
        return []

    journal_entries = journal if journal is not None else load_resolution_journal(xdg_base=xdg_base)
    listings: list[ReferenceListing] = []
    for ref, entry in sorted(document.entries.items()):
        principal = (
            {"profile": entry.account or ref, "account": entry.account}
            if entry.account
            else {"profile": ref, "account": None}
        )
        listings.append(
            ReferenceListing(
                ref=ref,
                backend=entry.backend,
                scopes={
                    "allowedRepos": entry.allowed_repos,
                    "allowedProjectIds": entry.allowed_project_ids,
                    "allowedEndpoints": entry.allowed_endpoints,
                },
                principal=principal,
                last_successful_resolution=last_successful_resolution(
                    ref,
                    journal=journal_entries,
                    xdg_base=xdg_base,
                ),
            )
        )
    return listings


def _register_environment_backend(
    *,
    root: Path,
    selector_path: Path | None,
    xdg_base: Path | None,
    environ: Mapping[str, str] | None,
) -> None:
    adapter = EnvironmentBackendAdapter(
        repository_root=root,
        selector_path=selector_path,
        xdg_base=xdg_base,
        environ=environ,
    )
    register_backend_adapter("environment", adapter)


def _repository_context_for_surface(
    root: Path,
    cfg: Mapping[str, Any],
    *,
    surface: str,
    destination_endpoint: str,
) -> tuple[RepositoryContext, str]:
    from host_lib import git_remote_url, host_section, parse_owner_repo, remote_name

    remote = remote_name(cfg)
    remote_url = git_remote_url(root, remote) or remote
    parsed = parse_owner_repo(remote_url if isinstance(remote_url, str) else None)
    repo_slug = f"{parsed[0]}/{parsed[1]}" if parsed else ""
    project_id = cfg.get("projectId")
    project_id_str = project_id.strip() if isinstance(project_id, str) and project_id.strip() else "unpaired"
    return (
        RepositoryContext(
            remote=remote_url,
            repo_slug=repo_slug,
            project_id=project_id_str,
            destination_endpoint=destination_endpoint,
        ),
        remote_url,
    )


def _destination_for_surface(
    cfg: Mapping[str, Any],
    surface: str,
    *,
    root: Path,
) -> str:
    from host_lib import _api_base_for_provider, host_section

    if surface == "memory":
        from memory_lib import memory_rest_base

        return memory_rest_base(dict(cfg))

    host = host_section(cfg)
    provider = str(host.get("provider") or "github")
    if surface == "host":
        return _api_base_for_provider(host, provider) or "https://api.github.com"
    if surface == "planning":
        from planning_store import _issues_destination_endpoint, resolve_issues_provider

        issues_provider = str(resolve_issues_provider(cfg).get("provider") or "github-issues")
        return _issues_destination_endpoint(cfg, issues_provider) or "https://api.github.com"
    return "https://api.github.com"


def _purpose_for_surface(surface: str) -> str:
    if surface == "host":
        return "host"
    if surface == "planning":
        return "planning"
    return "api"


def _provider_for_surface(
    cfg: Mapping[str, Any],
    surface: str,
    *,
    root: Path,
) -> str:
    from host_lib import host_section

    if surface == "memory":
        from memory_sot import resolve_memory_provider

        provider = resolve_memory_provider(root, dict(cfg)) or "recallium"
        return provider if provider != "none" else "recallium"

    host = host_section(cfg)
    if surface == "planning":
        from planning_store import _ISSUES_PROVIDER_TO_BROKER, resolve_issues_provider

        issues_provider = str(resolve_issues_provider(cfg).get("provider") or "github-issues")
        broker = _ISSUES_PROVIDER_TO_BROKER.get(issues_provider, issues_provider)
        return broker if broker not in {"", "none"} else "github"
    provider = str(host.get("provider") or "github")
    return provider if provider != "none" else "github"


def diagnose_surface(
    root: Path,
    cfg: Mapping[str, Any],
    surface_binding: ResolvedCredentialSurface,
    *,
    selector_path: Path | None = None,
    pairing_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
    environ: Mapping[str, str] | None = None,
    register_env_backend: bool = True,
    config_notices: tuple[str, ...] = (),
) -> SurfaceDiagnosis:
    surface_notices = _notices_for_surface(surface_binding, config_notices)
    context, remote_url = _repository_context_for_surface(
        root,
        cfg,
        surface=surface_binding.surface,
        destination_endpoint=_destination_for_surface(cfg, surface_binding.surface, root=root),
    )
    credential_ref = surface_binding.credential_ref
    if credential_ref is None and surface_binding.token_env:
        credential_ref = f"tokenEnv:{surface_binding.token_env}"

    if credential_ref is None:
        return SurfaceDiagnosis(
            surface=surface_binding.surface,
            repository=remote_url,
            project_id=context.project_id,
            credential_ref=None,
            resolved_principal=None,
            scope_binding=None,
            pairing={"verdict": "absent", "approved": False},
            repository_access="skipped",
            required_operation_verdict="skipped",
            notices=surface_notices,
        )

    if register_env_backend:
        _register_environment_backend(
            root=root,
            selector_path=selector_path,
            xdg_base=xdg_base if selector_path is None else None,
            environ=environ,
        )

    selector_document: SelectorDocument | None = None
    selector_entry: SelectorEntry | None = None
    failure: DoctorFailure | None = None

    try:
        selector_document = load_selector_store(
            path=selector_path,
            xdg_base=xdg_base if selector_path is None else None,
            skip_integrity=skip_integrity,
        )
        if not str(credential_ref).startswith("tokenEnv:"):
            selector_entry = selector_document.entries.get(credential_ref)
    except SelectorStoreError as exc:
        if exc.code == "selector-absent":
            remediation = remediation_for_code(fc.MISSING_SELECTOR, root=root)
            failure = DoctorFailure(code=fc.MISSING_SELECTOR, remediation=remediation)
        else:
            remediation = remediation_for_code(fc.INSUFFICIENT_SCOPE, root=root)
            failure = DoctorFailure(code=exc.code, remediation=remediation)

    pairing = _pairing_report(
        credential_ref if not str(credential_ref).startswith("tokenEnv:") else "",
        context,
        pairing_path=pairing_path,
        xdg_base=xdg_base if pairing_path is None else None,
        skip_integrity=skip_integrity,
    )

    if failure is not None:
        return SurfaceDiagnosis(
            surface=surface_binding.surface,
            repository=remote_url,
            project_id=context.project_id,
            credential_ref=credential_ref,
            resolved_principal=None,
            scope_binding=_scope_binding(selector_entry),
            pairing=pairing,
            repository_access="fail",
            required_operation_verdict="fail",
            failure=failure,
            notices=surface_notices,
        )

    if str(credential_ref).startswith("tokenEnv:"):
        token_env = surface_binding.token_env or ""
        source = environ if environ is not None else os.environ
        if token_env and source.get(token_env, "").strip():
            return SurfaceDiagnosis(
                surface=surface_binding.surface,
                repository=remote_url,
                project_id=context.project_id,
                credential_ref=credential_ref,
                resolved_principal=None,
                scope_binding=None,
                pairing=pairing,
                repository_access="ok",
                required_operation_verdict="pass",
                notices=surface_notices,
            )
        remediation = remediation_for_code(fc.INSUFFICIENT_ACCESS, root=root)
        return SurfaceDiagnosis(
            surface=surface_binding.surface,
            repository=remote_url,
            project_id=context.project_id,
            credential_ref=credential_ref,
            resolved_principal=None,
            scope_binding=None,
            pairing=pairing,
            repository_access="fail",
            required_operation_verdict="fail",
            failure=DoctorFailure(code=fc.INSUFFICIENT_ACCESS, remediation=remediation),
            notices=surface_notices,
        )

    lookup = resolve_lookup(
        CredentialRef(credential_ref),
        provider=_provider_for_surface(cfg, surface_binding.surface, root=root),
        purpose=_purpose_for_surface(surface_binding.surface),
        context=context,
        selector_path=selector_path,
        pairing_path=pairing_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
    )

    principal = lookup.principal
    if lookup.resolution.state is ResolutionState.RESOLVED:
        if lookup.resolution.token and lookup.resolution.token.principal:
            principal = lookup.resolution.token.principal
        record_successful_resolution(
            credential_ref,
            principal,
            path=default_resolution_journal_path(xdg_base=xdg_base if pairing_path is None else None),
            xdg_base=xdg_base if pairing_path is None else None,
        )
        return SurfaceDiagnosis(
            surface=surface_binding.surface,
            repository=remote_url,
            project_id=context.project_id,
            credential_ref=credential_ref,
            resolved_principal=_principal_public(principal),
            scope_binding=_scope_binding(selector_entry),
            pairing=pairing,
            repository_access="ok",
            required_operation_verdict="pass",
            notices=surface_notices,
        )

    if lookup.resolution.state is ResolutionState.EXPLICITLY_NO_AUTH:
        return SurfaceDiagnosis(
            surface=surface_binding.surface,
            repository=remote_url,
            project_id=context.project_id,
            credential_ref=credential_ref,
            resolved_principal=_principal_public(principal),
            scope_binding=_scope_binding(selector_entry),
            pairing=pairing,
            repository_access="ok",
            required_operation_verdict="pass",
            notices=surface_notices,
        )

    code = lookup.failure_code or lookup.resolution.reason or fc.UNAVAILABLE_BACKEND
    remediation = remediation_for_code(code, root=root)
    return SurfaceDiagnosis(
        surface=surface_binding.surface,
        repository=remote_url,
        project_id=context.project_id,
        credential_ref=credential_ref,
        resolved_principal=_principal_public(principal),
        scope_binding=_scope_binding(selector_entry),
        pairing=pairing,
        repository_access="fail",
        required_operation_verdict="fail",
        failure=DoctorFailure(code=code, remediation=remediation),
        notices=surface_notices,
    )


def _config_surface_failure(root: Path, exc: ConfigSurfaceError) -> DoctorFailure:
    remediation = remediation_for_code(exc.code, root=root)
    if exc.code not in fc.ALL_FAILURE_CODES:
        remediation = Remediation(
            scope=LOCAL_SCOPE,
            command=remediation_command(scope=LOCAL_SCOPE, code=exc.code, root=root),
        )
    return DoctorFailure(code=exc.code, remediation=remediation)


def diagnose_repository(
    root: Path,
    *,
    selector_path: Path | None = None,
    pairing_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
    environ: Mapping[str, str] | None = None,
    register_env_backend: bool = True,
) -> dict[str, Any]:
    from host_lib import load_workflow_config

    cfg = load_workflow_config(root)
    try:
        surface_result = resolve_config_surface(cfg, deprecation_phase=DeprecationPhase.DEPRECATION)
    except ConfigSurfaceError as exc:
        failure = _config_surface_failure(root, exc)
        return {
            "verdict": "fail",
            "projectId": None,
            "surfaces": [],
            "references": [
                _reference_to_dict(item)
                for item in list_known_references(
                    selector_path=selector_path,
                    xdg_base=xdg_base,
                    skip_integrity=skip_integrity,
                )
            ],
            "credentialDoctor": f"{CREDENTIAL_DOCTOR_CLI} --root {root.resolve()}",
            "failure": {
                "code": failure.code,
                "remediationScope": failure.remediation.scope,
                "remediationCommand": failure.remediation.command,
            },
        }
    surfaces = [
        diagnose_surface(
            root,
            cfg,
            surface_result.host,
            selector_path=selector_path,
            pairing_path=pairing_path,
            xdg_base=xdg_base,
            skip_integrity=skip_integrity,
            environ=environ,
            register_env_backend=register_env_backend,
            config_notices=surface_result.notices,
        ),
        diagnose_surface(
            root,
            cfg,
            surface_result.planning,
            selector_path=selector_path,
            pairing_path=pairing_path,
            xdg_base=xdg_base,
            skip_integrity=skip_integrity,
            environ=environ,
            register_env_backend=register_env_backend,
            config_notices=surface_result.notices,
        ),
        diagnose_surface(
            root,
            cfg,
            surface_result.memory,
            selector_path=selector_path,
            pairing_path=pairing_path,
            xdg_base=xdg_base,
            skip_integrity=skip_integrity,
            environ=environ,
            register_env_backend=register_env_backend,
            config_notices=surface_result.notices,
        ),
    ]
    references = list_known_references(
        selector_path=selector_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
    )
    failures = [surface.failure for surface in surfaces if surface.failure is not None]
    verdict = "ok"
    if failures:
        verdict = "fail"
    elif any(surface.required_operation_verdict == "fail" for surface in surfaces):
        verdict = "fail"

    return {
        "verdict": verdict,
        "projectId": surface_result.project_id,
        "surfaces": [_surface_to_dict(surface) for surface in surfaces],
        "references": [_reference_to_dict(item) for item in references],
        "credentialDoctor": f"{CREDENTIAL_DOCTOR_CLI} --root {root.resolve()}",
    }


def diagnose_host_surface(
    root: Path,
    *,
    selector_path: Path | None = None,
    pairing_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Host-doctor integration: principal + required-operation verdict only."""
    from host_lib import load_workflow_config

    cfg = load_workflow_config(root)
    try:
        surface_result = resolve_config_surface(cfg, deprecation_phase=DeprecationPhase.DEPRECATION)
    except ConfigSurfaceError as exc:
        failure = _config_surface_failure(root, exc)
        return {
            "principal": None,
            "requiredOperationVerdict": "fail",
            "repositoryAccess": "fail",
            "credentialRef": None,
            "credentialDoctor": f"{CREDENTIAL_DOCTOR_CLI} --root {root.resolve()}",
            "failure": {
                "code": failure.code,
                "remediationScope": failure.remediation.scope,
                "remediationCommand": failure.remediation.command,
            },
        }
    diagnosis = diagnose_surface(
        root,
        cfg,
        surface_result.host,
        selector_path=selector_path,
        pairing_path=pairing_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
        environ=environ,
    )
    payload = {
        "principal": diagnosis.resolved_principal,
        "requiredOperationVerdict": diagnosis.required_operation_verdict,
        "repositoryAccess": diagnosis.repository_access,
        "credentialRef": diagnosis.credential_ref,
        "credentialDoctor": f"{CREDENTIAL_DOCTOR_CLI} --root {root.resolve()}",
    }
    if diagnosis.failure is not None:
        payload["failure"] = {
            "code": diagnosis.failure.code,
            "remediationScope": diagnosis.failure.remediation.scope,
            "remediationCommand": diagnosis.failure.remediation.command,
        }
    return payload


def classify_legacy_surface(
    root: Path,
    surface_binding: ResolvedCredentialSurface,
    *,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LegacyClassification:
    """Classify a legacy or transitional credential surface."""
    if surface_binding.source == "credentialRef" and surface_binding.credential_ref:
        local = try_load_local_selector(selector_path=selector_path, xdg_base=xdg_base)
        if local is None:
            return LegacyClassification.NEEDS_LOCAL_SELECTOR
        entry = local.entries.get(surface_binding.credential_ref)
        if entry is None:
            return LegacyClassification.NEEDS_LOCAL_SELECTOR
        if entry.backend == "environment":
            if not is_environment_backend_declared(
                surface_binding.credential_ref,
                root=root,
                selector_path=selector_path,
                xdg_base=xdg_base,
            ):
                return LegacyClassification.NEEDS_CI_DECLARATION
        return LegacyClassification.READY

    if surface_binding.source == "tokenEnv-alias" and surface_binding.token_env:
        local = try_load_local_selector(selector_path=selector_path, xdg_base=xdg_base)
        ci = try_load_ci_selector(root=root)
        source = environ if environ is not None else os.environ
        token_present = bool(source.get(surface_binding.token_env, "").strip())
        if is_github_actions(source) and not local and not ci:
            return LegacyClassification.NEEDS_CI_DECLARATION
        if local is not None or ci is not None:
            return LegacyClassification.READY if token_present else LegacyClassification.NEEDS_LOCAL_SELECTOR
        return LegacyClassification.NEEDS_LOCAL_SELECTOR

    return LegacyClassification.READY


def release_blocking_alias_preflight(
    root: Path,
    *,
    token_env: str,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Refuse alias removal until both local and CI resolution are proven."""
    result = deprecation_release_preflight(
        root=root,
        token_env=token_env,
        environ=environ,
        selector_path=selector_path,
        xdg_base=xdg_base,
    )
    local_ready = result.local_declared
    ci_ready = result.ci_declared
    alias_removal_allowed = local_ready and ci_ready and result.verdict == "pass"
    return {
        "verdict": result.verdict,
        "code": result.code,
        "remediationScope": CI_SCOPE if not ci_ready else LOCAL_SCOPE,
        "remediationCommand": (
            remediation_command(scope=CI_SCOPE, code=fc.MISSING_CI_DECLARATION, root=root)
            if not ci_ready
            else remediation_command(scope=LOCAL_SCOPE, code=fc.MISSING_SELECTOR, root=root)
        ),
        "localDeclared": local_ready,
        "ciDeclared": ci_ready,
        "aliasRemovalAllowed": alias_removal_allowed,
        "ambientFinding": (
            {
                "detected": result.ambient_finding.detected,
                "tokenEnv": result.ambient_finding.token_env,
                "remediation": result.ambient_finding.remediation,
            }
            if result.ambient_finding is not None
            else None
        ),
    }


def remediate(
    *,
    scope: str,
    code: str,
    root: Path,
    selector_path: Path | None = None,
    xdg_base: Path | None = None,
) -> dict[str, Any]:
    """Execute or describe remediation for a failure code."""
    if scope == LOCAL_SCOPE and code == fc.MISSING_SELECTOR:
        path = selector_path or default_selector_path(xdg_base=xdg_base)
        if not path.parent.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            os.chmod(path.parent, 0o700)
        if not path.is_file():
            template = {"version": 1, "entries": {}}
            path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
            os.chmod(path, 0o600)
        return {"verdict": "ok", "action": "write-local-selector", "path": str(path)}

    if scope == CI_SCOPE and code == fc.MISSING_CI_DECLARATION:
        ci_path = root / CI_SELECTOR_RELATIVE
        if not ci_path.parent.exists():
            ci_path.parent.mkdir(parents=True, exist_ok=True)
        if not ci_path.is_file():
            template = {"version": 1, "entries": {}}
            ci_path.write_text(json.dumps(template, indent=2) + "\n", encoding="utf-8")
        return {"verdict": "ok", "action": "write-ci-selector", "path": str(ci_path)}

    return {
        "verdict": "noop",
        "scope": scope,
        "code": code,
        "hint": fc.failure_detail(code).hint,
    }


def _surface_to_dict(surface: SurfaceDiagnosis) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "surface": surface.surface,
        "repository": surface.repository,
        "projectId": surface.project_id,
        "credentialRef": surface.credential_ref,
        "resolvedPrincipal": surface.resolved_principal,
        "scopeBinding": surface.scope_binding,
        "pairing": surface.pairing,
        "repositoryAccess": surface.repository_access,
        "requiredOperationVerdict": surface.required_operation_verdict,
        "notices": list(surface.notices),
    }
    if surface.failure is not None:
        payload["failure"] = {
            "code": surface.failure.code,
            "remediationScope": surface.failure.remediation.scope,
            "remediationCommand": surface.failure.remediation.command,
        }
    return payload


def _reference_to_dict(item: ReferenceListing) -> dict[str, Any]:
    return {
        "ref": item.ref,
        "backend": item.backend,
        "scopes": item.scopes,
        "principal": item.principal,
        "lastSuccessfulResolution": item.last_successful_resolution,
    }
