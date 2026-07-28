"""Run-bound identity probe (PRD 080 phase 13 / R3, R9).

Probes once per run id, pins the resolved principal into the repository context
binding, prohibits TTL-based caching of probe verdicts, and leaves the mutating
call as the authoritative authorization check.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, TypeVar

from credentials.failure_codes import PRINCIPAL_MISMATCH, failure_detail
from credentials.model import Principal

T = TypeVar("T")

AUTHORITATIVE_AUTHZ: Final[str] = "mutating-call"

PROBE_NO_PRINCIPAL: Final[str] = "probe-no-principal"
PROBE_MISSING_RUN_ID: Final[str] = "probe-missing-run-id"
PROBE_TTL_CACHE_REJECTED: Final[str] = "probe-ttl-cache-rejected"

_NO_PRINCIPAL_HINT: Final[str] = (
    "supply a resolved principal for this run before any mutating host operation"
)
_MISSING_RUN_ID_HINT: Final[str] = (
    "bind a non-empty run id on the repository context before probing identity"
)
_TTL_HINT: Final[str] = (
    "identity probe verdicts are run-bound only; TTL caches are prohibited to prevent TOCTOU grants"
)


class IdentityProbeError(Exception):
    """Fail-closed identity probe error with a stable code and actionable report."""

    def __init__(self, code: str, hint: str, *, report: str | None = None) -> None:
        self.code = code
        self.hint = hint
        self.report = report or f"{code}: {hint}"
        super().__init__(self.report)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of a run-bound identity probe (never a grant)."""

    run_id: str
    principal: Principal | None
    reused: bool
    blocked: bool
    code: str | None = None
    report: str | None = None
    authoritative_authorization: str = AUTHORITATIVE_AUTHZ


@dataclass(frozen=True, slots=True)
class ContextPrincipalBinding:
    """Repository context with a run-pinned non-secret principal."""

    run_id: str
    context: Any
    principal: Principal


def _require_run_id(run_id: str | None, context: Any | None = None) -> str:
    rid = (run_id or "").strip()
    if not rid and context is not None:
        raw = getattr(context, "run_id", None)
        rid = str(raw or "").strip()
    if not rid:
        raise IdentityProbeError(PROBE_MISSING_RUN_ID, _MISSING_RUN_ID_HINT)
    return rid


def _principals_match(left: Principal, right: Principal) -> bool:
    return left.profile == right.profile and left.account == right.account


def _mismatch_report(*, expected: Principal, observed: Principal) -> str:
    detail = failure_detail(PRINCIPAL_MISMATCH)
    return (
        f"{detail.code}: expected principal {expected!s} but observed {observed!s}; "
        f"{detail.hint}. Blocking before any mutating operation."
    )


def _no_principal_report() -> str:
    return f"{PROBE_NO_PRINCIPAL}: {_NO_PRINCIPAL_HINT}"


class IdentityProbe:
    """In-process run-bound probe registry.

    Pins one principal per run id. Does not cache by wall-clock TTL. Probe success
    is never treated as authorization — callers must re-check at the mutating call.
    """

    def __init__(self) -> None:
        self._pins: dict[str, Principal] = {}
        self._probe_invocations: dict[str, int] = {}

    def pinned_principal(self, run_id: str) -> Principal | None:
        return self._pins.get(str(run_id).strip())

    def pin_into_context(self, context: Any, principal: Principal) -> ContextPrincipalBinding:
        """Pin the resolved principal for the context's run id."""
        rid = _require_run_id(None, context)
        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        existing = self._pins.get(rid)
        if existing is not None and not _principals_match(existing, principal):
            report = _mismatch_report(expected=existing, observed=principal)
            raise IdentityProbeError(PRINCIPAL_MISMATCH, failure_detail(PRINCIPAL_MISMATCH).hint, report=report)
        self._pins[rid] = principal
        return ContextPrincipalBinding(run_id=rid, context=context, principal=principal)

    def probe(
        self,
        *,
        run_id: str | None = None,
        context: Any | None = None,
        observed: Principal | None = None,
        expected: Principal | None = None,
    ) -> ProbeResult:
        """Probe identity for a run.

        - No principal → blocked with actionable report.
        - Matching principal → pin (or reuse) for this run id.
        - Mismatch → blocked with actionable report; no pin update.
        """
        rid = _require_run_id(run_id, context)
        self._probe_invocations[rid] = self._probe_invocations.get(rid, 0) + 1

        pinned = self._pins.get(rid)
        if pinned is not None:
            if expected is not None and not _principals_match(pinned, expected):
                report = _mismatch_report(expected=expected, observed=pinned)
                return ProbeResult(
                    run_id=rid,
                    principal=pinned,
                    reused=True,
                    blocked=True,
                    code=PRINCIPAL_MISMATCH,
                    report=report,
                )
            if observed is not None and not _principals_match(pinned, observed):
                report = _mismatch_report(expected=pinned, observed=observed)
                return ProbeResult(
                    run_id=rid,
                    principal=pinned,
                    reused=True,
                    blocked=True,
                    code=PRINCIPAL_MISMATCH,
                    report=report,
                )
            return ProbeResult(
                run_id=rid,
                principal=pinned,
                reused=True,
                blocked=False,
            )

        candidate = observed if observed is not None else expected
        if candidate is None:
            report = _no_principal_report()
            return ProbeResult(
                run_id=rid,
                principal=None,
                reused=False,
                blocked=True,
                code=PROBE_NO_PRINCIPAL,
                report=report,
            )

        if expected is not None and observed is not None and not _principals_match(expected, observed):
            report = _mismatch_report(expected=expected, observed=observed)
            return ProbeResult(
                run_id=rid,
                principal=None,
                reused=False,
                blocked=True,
                code=PRINCIPAL_MISMATCH,
                report=report,
            )

        if expected is not None and observed is None:
            candidate = expected
        elif observed is not None and expected is None:
            candidate = observed

        self._pins[rid] = candidate
        if context is not None:
            self.pin_into_context(context, candidate)
        return ProbeResult(
            run_id=rid,
            principal=candidate,
            reused=False,
            blocked=False,
        )

    def require_probe(
        self,
        *,
        run_id: str | None = None,
        context: Any | None = None,
        observed: Principal | None = None,
        expected: Principal | None = None,
    ) -> ProbeResult:
        """Probe and raise when blocked."""
        result = self.probe(
            run_id=run_id,
            context=context,
            observed=observed,
            expected=expected,
        )
        if result.blocked:
            raise IdentityProbeError(
                result.code or PROBE_NO_PRINCIPAL,
                result.report or _NO_PRINCIPAL_HINT,
                report=result.report,
            )
        return result

    def write_ttl_cache(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        """Reject any attempt to persist a TTL-cached probe verdict."""
        raise IdentityProbeError(PROBE_TTL_CACHE_REJECTED, _TTL_HINT)

    def cache_verdict_with_ttl(
        self,
        *_args: Any,
        ttl_seconds: float | int | None = None,
        **_kwargs: Any,
    ) -> None:
        """Alias rejection surface for TTL cache writes (TOCTOU prevention)."""
        del ttl_seconds
        self.write_ttl_cache()

    def authorize_mutating_call(
        self,
        mutate: Callable[[], T],
        *,
        run_id: str | None = None,
        context: Any | None = None,
        observed: Principal | None = None,
        expected: Principal | None = None,
    ) -> T:
        """Run the mutating call only after a non-blocked probe.

        The mutating call remains the authoritative authorization check — this
        method only enforces that a prior/current probe has pinned a matching
        principal for the run and does not treat probe success as a grant.
        """
        result = self.require_probe(
            run_id=run_id,
            context=context,
            observed=observed,
            expected=expected,
        )
        if result.authoritative_authorization != AUTHORITATIVE_AUTHZ:
            raise IdentityProbeError(
                "probe-authz-contract",
                "identity probe must defer authorization to the mutating call",
            )
        return mutate()

    def invocation_count(self, run_id: str) -> int:
        return self._probe_invocations.get(str(run_id).strip(), 0)

    def clear(self) -> None:
        self._pins.clear()
        self._probe_invocations.clear()


_DEFAULT_PROBE = IdentityProbe()


def probe_identity(
    *,
    run_id: str | None = None,
    context: Any | None = None,
    observed: Principal | None = None,
    expected: Principal | None = None,
    registry: IdentityProbe | None = None,
) -> ProbeResult:
    return (registry or _DEFAULT_PROBE).probe(
        run_id=run_id,
        context=context,
        observed=observed,
        expected=expected,
    )


def require_identity(
    *,
    run_id: str | None = None,
    context: Any | None = None,
    observed: Principal | None = None,
    expected: Principal | None = None,
    registry: IdentityProbe | None = None,
) -> ProbeResult:
    return (registry or _DEFAULT_PROBE).require_probe(
        run_id=run_id,
        context=context,
        observed=observed,
        expected=expected,
    )


def reject_ttl_cache(
    *args: Any,
    registry: IdentityProbe | None = None,
    **kwargs: Any,
) -> None:
    (registry or _DEFAULT_PROBE).write_ttl_cache(*args, **kwargs)


def authorize_mutating_call(
    mutate: Callable[[], T],
    *,
    run_id: str | None = None,
    context: Any | None = None,
    observed: Principal | None = None,
    expected: Principal | None = None,
    registry: IdentityProbe | None = None,
) -> T:
    return (registry or _DEFAULT_PROBE).authorize_mutating_call(
        mutate,
        run_id=run_id,
        context=context,
        observed=observed,
        expected=expected,
    )


def pin_principal(
    context: Any,
    principal: Principal,
    *,
    registry: IdentityProbe | None = None,
) -> ContextPrincipalBinding:
    return (registry or _DEFAULT_PROBE).pin_into_context(context, principal)


def probe_bindings(registry: IdentityProbe | None = None) -> Mapping[str, Principal]:
    """Read-only view of run-id → pinned principal (tests / diagnostics)."""
    source = registry or _DEFAULT_PROBE
    return dict(source._pins)
