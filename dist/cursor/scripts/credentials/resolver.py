"""Broker resolver with fail-closed scope, tri-state outcomes, and lookup timeouts (PRD 080 phase 5 / R3)."""

from __future__ import annotations

import logging
import os
import re
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from credentials import failure_codes as fc
from credentials.backends import load_backend
from credentials.ci_declaration import try_load_ci_selector
from credentials.endpoint_guard import EndpointGuardError, normalize_allowed_hosts, validate_destination
from credentials.model import CredentialRef, Principal, Resolution, ResolutionState, ResolvedToken, Secret
from credentials.pairing_store import PairingVerdict, check_pairing
from credentials.selector_store import SelectorDocument, SelectorEntry, SelectorStoreError, load_selector_store

logger = logging.getLogger(__name__)

DEFAULT_LOOKUP_TIMEOUT_SECONDS: Final[float] = 10.0
_NO_AUTH_PURPOSES: Final[frozenset[str]] = frozenset({"public", "no-auth", "explicitly-no-auth"})
_GIT_REMOTE_RE = re.compile(
    r"(?:https?://[^/]+/|git@[^:]+:)(?P<slug>[^/]+/[^/]+?)(?:\.git)?/?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    """Non-secret repository identity used for scope enforcement."""

    remote: str
    repo_slug: str
    project_id: str
    destination_endpoint: str


@dataclass(frozen=True, slots=True)
class BackendResolveResult:
    state: ResolutionState
    token: Secret | None = None
    principal: Principal | None = None
    failure_code: str | None = None
    backend: str | None = None


@dataclass(frozen=True, slots=True)
class ResolverResult:
    resolution: Resolution
    failure_code: str | None = None
    backend: str | None = None
    principal: Principal | None = None
    legitimate_halt: bool = False
    halt_cause: str | None = None

    def format_log_line(self) -> str:
        profile = self.principal.profile if self.principal else "none"
        account = self.principal.account if self.principal and self.principal.account else "none"
        backend = self.backend or "none"
        return f"resolver backend={backend} profile={profile} account={account}"


class BackendAdapter(Protocol):
    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult: ...


class _UnavailableBackendAdapter:
    def resolve(
        self,
        entry: SelectorEntry,
        *,
        purpose: str,
        context: RepositoryContext,
    ) -> BackendResolveResult:
        _ = (entry, purpose, context)
        return BackendResolveResult(
            state=ResolutionState.UNRESOLVED,
            failure_code=fc.UNAVAILABLE_BACKEND,
            backend=entry.backend,
        )


_BACKEND_ADAPTERS: dict[str, BackendAdapter] = {
    "environment": _UnavailableBackendAdapter(),
    "github_cli": _UnavailableBackendAdapter(),
    "git_credential": _UnavailableBackendAdapter(),
    "keystore": _UnavailableBackendAdapter(),
}
_LAZY_REGISTRATION_ENABLED: bool = True


def register_backend_adapter(backend: str, adapter: BackendAdapter) -> None:
    _BACKEND_ADAPTERS[backend] = adapter


def clear_backend_adapters(*, disable_lazy: bool = True) -> None:
    """Reset every adapter to the unavailable placeholder.

    `disable_lazy` keeps a cleared registry cleared, so isolation in tests is not undone by
    on-demand registration.
    """
    global _LAZY_REGISTRATION_ENABLED
    for backend in tuple(_BACKEND_ADAPTERS):
        _BACKEND_ADAPTERS[backend] = _UnavailableBackendAdapter()
    _LAZY_REGISTRATION_ENABLED = not disable_lazy


def backend_adapter(backend: str) -> BackendAdapter:
    """Return the adapter for a backend, registering it on demand when none is bound yet."""
    adapter = _BACKEND_ADAPTERS.get(backend)
    if adapter is not None and not isinstance(adapter, _UnavailableBackendAdapter):
        return adapter
    if not _LAZY_REGISTRATION_ENABLED:
        return adapter or _UnavailableBackendAdapter()
    try:
        load_backend(backend)()
    except (ImportError, ValueError):
        logger.warning("credential backend %s could not be registered", backend)
        return adapter or _UnavailableBackendAdapter()
    return _BACKEND_ADAPTERS.get(backend) or _UnavailableBackendAdapter()


def lookup_timeout_seconds() -> float:
    raw = os.environ.get("SW_CREDENTIAL_LOOKUP_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return DEFAULT_LOOKUP_TIMEOUT_SECONDS
    try:
        return max(0.1, float(raw))
    except ValueError:
        return DEFAULT_LOOKUP_TIMEOUT_SECONDS


def repo_slug_from_remote(remote: str) -> str:
    value = str(remote).strip()
    if not value:
        return ""
    match = _GIT_REMOTE_RE.search(value)
    if match:
        return match.group("slug")
    if "/" in value and "://" not in value and "@" not in value:
        return value.strip("/")
    return value


def _endpoint_in_scope(destination: str, allowed_endpoints: tuple[str, ...]) -> bool:
    destination = destination.strip()
    if not destination:
        return False
    for allowed in allowed_endpoints:
        candidate = allowed.strip()
        if not candidate:
            continue
        if destination == candidate or destination.startswith(candidate.rstrip("/") + "/"):
            return True
        try:
            validate_destination(destination, normalize_allowed_hosts([urllib.parse.urlparse(candidate).hostname or ""]))
            if destination.startswith(candidate.split("://", 1)[0] + "://"):
                allowed_host = (urllib.parse.urlparse(candidate).hostname or "").lower()
                dest_host = (urllib.parse.urlparse(destination).hostname or "").lower()
                if allowed_host and dest_host == allowed_host:
                    return True
        except EndpointGuardError:
            continue
    return False


def _repo_in_scope(repo_slug: str, allowed_repos: tuple[str, ...]) -> bool:
    normalized = repo_slug.strip().lower()
    return any(normalized == item.strip().lower() for item in allowed_repos)


def _project_in_scope(project_id: str, allowed_project_ids: tuple[str, ...]) -> bool:
    normalized = project_id.strip()
    return any(normalized == item.strip() for item in allowed_project_ids)


def _detect_repo_root(start: Path | None = None) -> Path | None:
    """Walk up from *start* (default: cwd) looking for a .git directory or file."""
    current = (start or Path.cwd()).resolve()
    while True:
        if (current / ".git").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _load_selector(
    *,
    selector_path: Path | None,
    xdg_base: Path | None,
    skip_integrity: bool,
    repo_root: Path | None = None,
) -> SelectorDocument:
    try:
        return load_selector_store(path=selector_path, xdg_base=xdg_base, skip_integrity=skip_integrity)
    except SelectorStoreError as exc:
        if exc.code == "selector-absent":
            # Consult the committed CI selector before failing closed (R3).
            root = repo_root if repo_root is not None else _detect_repo_root()
            if root is not None:
                ci_doc = try_load_ci_selector(root=root)
                if ci_doc is not None:
                    return ci_doc
            raise ResolverScopeError(fc.MISSING_SELECTOR, exc.hint) from exc
        if exc.code.startswith("selector-missing-"):
            raise ResolverScopeError(fc.INSUFFICIENT_SCOPE, exc.hint) from exc
        raise ResolverScopeError(fc.INSUFFICIENT_SCOPE, exc.hint) from exc


class ResolverScopeError(Exception):
    def __init__(self, code: str, hint: str) -> None:
        self.code = code
        self.hint = hint
        super().__init__(fc.failure_detail(code, hint=hint).hint)


def _enforce_scope(entry: SelectorEntry, context: RepositoryContext) -> None:
    if not _repo_in_scope(context.repo_slug, entry.allowed_repos):
        detail = fc.failure_detail(fc.OUT_OF_SCOPE_REPO)
        raise ResolverScopeError(detail.code, detail.hint)
    if not _project_in_scope(context.project_id, entry.allowed_project_ids):
        detail = fc.failure_detail(fc.OUT_OF_SCOPE_PROJECT)
        raise ResolverScopeError(detail.code, detail.hint)
    if not _endpoint_in_scope(context.destination_endpoint, entry.allowed_endpoints):
        detail = fc.failure_detail(fc.OUT_OF_SCOPE_ENDPOINT)
        raise ResolverScopeError(detail.code, detail.hint)


def _check_pairing(
    ref: str,
    context: RepositoryContext,
    *,
    pairing_path: Path | None,
    xdg_base: Path | None,
    skip_integrity: bool,
) -> str | None:
    result = check_pairing(
        ref,
        context.project_id,
        context.remote,
        path=pairing_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
    )
    if result.verdict is PairingVerdict.ALLOWED:
        return None
    if result.verdict is PairingVerdict.MISMATCH:
        return fc.PAIRING_MISMATCH
    if result.verdict is PairingVerdict.UNAPPROVED:
        return fc.UNAPPROVED_PAIRING
    return fc.UNAPPROVED_PAIRING


def _invoke_backend(
    entry: SelectorEntry,
    *,
    purpose: str,
    context: RepositoryContext,
    timeout_seconds: float,
) -> BackendResolveResult:
    adapter = backend_adapter(entry.backend)

    def _call() -> BackendResolveResult:
        return adapter.resolve(entry, purpose=purpose, context=context)

    if timeout_seconds <= 0:
        return _call()

    pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="credential-resolve")
    future = pool.submit(_call)
    try:
        return future.result(timeout=timeout_seconds)
    except FuturesTimeoutError:
        pool.shutdown(wait=False, cancel_futures=True)
        return BackendResolveResult(
            state=ResolutionState.UNRESOLVED,
            failure_code=fc.LOOKUP_TIMEOUT,
            backend=entry.backend,
        )
    else:
        pool.shutdown(wait=False, cancel_futures=True)


def _backend_to_resolution(ref: CredentialRef, backend_result: BackendResolveResult) -> Resolution:
    if backend_result.state is ResolutionState.RESOLVED:
        if backend_result.token is None or not backend_result.token.value.strip():
            return Resolution.unresolved(ref, reason=fc.INSUFFICIENT_ACCESS)
        resolved = ResolvedToken(backend_result.token, backend_result.principal)
        return Resolution.resolved(ref, resolved)
    if backend_result.state is ResolutionState.EXPLICITLY_NO_AUTH:
        return Resolution.explicitly_no_auth(ref)
    return Resolution.unresolved(ref, reason=backend_result.failure_code or fc.UNAVAILABLE_BACKEND)


def resolve_lookup(
    ref: CredentialRef,
    *,
    provider: str | None = None,
    purpose: str | None = None,
    context: RepositoryContext | None = None,
    selector_path: Path | None = None,
    pairing_path: Path | None = None,
    xdg_base: Path | None = None,
    skip_integrity: bool = False,
    timeout_seconds: float | None = None,
) -> ResolverResult:
    if ref.is_empty:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=fc.EMPTY_REFERENCE),
            failure_code=fc.EMPTY_REFERENCE,
        )

    if not provider or not purpose or context is None:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=fc.MISSING_CONTEXT),
            failure_code=fc.MISSING_CONTEXT,
        )

    purpose_norm = purpose.strip().lower()
    provider_norm = provider.strip().lower()

    try:
        document = _load_selector(
            selector_path=selector_path,
            xdg_base=xdg_base,
            skip_integrity=skip_integrity,
        )
    except ResolverScopeError as exc:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=exc.code),
            failure_code=exc.code,
        )

    entry = document.entries.get(ref.value)
    if entry is None:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=fc.UNKNOWN_REF),
            failure_code=fc.UNKNOWN_REF,
        )

    if entry.provider.strip().lower() != provider_norm:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=fc.PROVIDER_MISMATCH),
            failure_code=fc.PROVIDER_MISMATCH,
            backend=entry.backend,
        )

    try:
        _enforce_scope(entry, context)
    except ResolverScopeError as exc:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=exc.code),
            failure_code=exc.code,
            backend=entry.backend,
        )

    pairing_code = _check_pairing(
        ref.value,
        context,
        pairing_path=pairing_path,
        xdg_base=xdg_base,
        skip_integrity=skip_integrity,
    )
    if pairing_code is not None:
        return ResolverResult(
            resolution=Resolution.unresolved(ref, reason=pairing_code),
            failure_code=pairing_code,
            backend=entry.backend,
        )

    if purpose_norm in _NO_AUTH_PURPOSES:
        resolution = Resolution.explicitly_no_auth(ref, reason="explicitly-no-auth")
        result = ResolverResult(
            resolution=resolution,
            backend=entry.backend,
            principal=Principal(profile=entry.account or entry.ref, account=entry.account),
        )
        logger.info(result.format_log_line())
        return result

    timeout = lookup_timeout_seconds() if timeout_seconds is None else timeout_seconds
    backend_result = _invoke_backend(entry, purpose=purpose_norm, context=context, timeout_seconds=timeout)
    resolution = _backend_to_resolution(ref, backend_result)
    failure_code = None if resolution.state is ResolutionState.RESOLVED else (
        backend_result.failure_code or resolution.reason
    )
    legitimate_halt = fc.is_legitimate_halt(failure_code)
    result = ResolverResult(
        resolution=resolution,
        failure_code=failure_code,
        backend=backend_result.backend or entry.backend,
        principal=backend_result.principal,
        legitimate_halt=legitimate_halt,
        halt_cause=failure_code if legitimate_halt else None,
    )
    logger.info(result.format_log_line())
    return result


def resolve(ref: CredentialRef, **context: object) -> Resolution:
    """Resolve a credential reference (backward-compatible entry point)."""
    provider = context.get("provider")
    purpose = context.get("purpose")
    repo_context = context.get("context")
    if not isinstance(provider, str) or not isinstance(purpose, str) or not isinstance(repo_context, RepositoryContext):
        if ref.is_empty:
            return Resolution.unresolved(ref, reason=fc.EMPTY_REFERENCE)
        return Resolution.unresolved(ref, reason=fc.MISSING_CONTEXT)
    selector_path = context.get("selector_path")
    pairing_path = context.get("pairing_path")
    xdg_base = context.get("xdg_base")
    skip_integrity = bool(context.get("skip_integrity"))
    timeout_seconds = context.get("timeout_seconds")
    return resolve_lookup(
        ref,
        provider=provider,
        purpose=purpose,
        context=repo_context,
        selector_path=selector_path if isinstance(selector_path, Path) else None,
        pairing_path=pairing_path if isinstance(pairing_path, Path) else None,
        xdg_base=xdg_base if isinstance(xdg_base, Path) else None,
        skip_integrity=skip_integrity,
        timeout_seconds=timeout_seconds if isinstance(timeout_seconds, (int, float)) else None,
    ).resolution
