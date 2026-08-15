#!/usr/bin/env python3
"""Bounded loop-until-dry execution with fingerprint-only persistence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Protocol

# Stable R7 convergence reason codes (PRD 270).
REASON_DRY_CLEAN = "r7.convergence.dry-clean"
REASON_DRY_ERROR = "r7.convergence.dry-error"
REASON_MAX_ROUNDS = "r7.convergence.max-rounds-exceeded"
REASON_TOKEN_BUDGET = "r7.convergence.token-budget"
REASON_FINDING_BUDGET = "r7.convergence.finding-budget"
REASON_MARGINAL_VALUE = "r7.convergence.marginal-value"
REASON_DUPLICATE_RATE = "r7.convergence.duplicate-rate"
REASON_DISCOVERY_ERROR = "r7.convergence.discovery-error"
REASON_TRUNCATED = "r7.convergence.truncated"
REASON_RATE_LIMITED = "r7.convergence.rate-limited"

CONVERGENCE_REASON_CODES = frozenset(
    {
        REASON_DRY_CLEAN,
        REASON_DRY_ERROR,
        REASON_MAX_ROUNDS,
        REASON_TOKEN_BUDGET,
        REASON_FINDING_BUDGET,
        REASON_MARGINAL_VALUE,
        REASON_DUPLICATE_RATE,
        REASON_DISCOVERY_ERROR,
        REASON_TRUNCATED,
        REASON_RATE_LIMITED,
    }
)

HEALTH_SUCCESS = "success"
HEALTH_ERROR = "error"
HEALTH_TRUNCATED = "truncated"
HEALTH_RATE_LIMITED = "rate-limited"


class ConvergenceError(RuntimeError):
    """Raised when convergence state cannot be read or safely persisted."""


@dataclass(frozen=True)
class ConvergenceBudgets:
    max_rounds: int
    max_findings: int
    max_tokens: int

    def __post_init__(self) -> None:
        for name, value in (
            ("max_rounds", self.max_rounds),
            ("max_findings", self.max_findings),
            ("max_tokens", self.max_tokens),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True)
class ConvergencePolicy:
    """Discretionary early-stop thresholds (R7)."""

    min_productive_rounds_for_discretionary: int = 2
    duplicate_rate_threshold: float = 0.75
    marginal_value_max_new: int = 1
    token_soft_stop_fraction: float = 0.9

    def __post_init__(self) -> None:
        if (
            isinstance(self.min_productive_rounds_for_discretionary, bool)
            or not isinstance(self.min_productive_rounds_for_discretionary, int)
            or self.min_productive_rounds_for_discretionary < 1
        ):
            raise ValueError("min_productive_rounds_for_discretionary must be >= 1")
        if not 0.0 < self.duplicate_rate_threshold <= 1.0:
            raise ValueError("duplicate_rate_threshold must be in (0, 1]")
        if (
            isinstance(self.marginal_value_max_new, bool)
            or not isinstance(self.marginal_value_max_new, int)
            or self.marginal_value_max_new < 0
        ):
            raise ValueError("marginal_value_max_new must be >= 0")
        if not 0.0 < self.token_soft_stop_fraction < 1.0:
            raise ValueError("token_soft_stop_fraction must be in (0, 1)")


@dataclass(frozen=True)
class Finding:
    """One discovery. Content remains transient; only its fingerprint persists."""

    content: Any
    tokens: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.tokens, bool) or not isinstance(self.tokens, int) or self.tokens < 0:
            raise ValueError("finding tokens must be a non-negative integer")


@dataclass(frozen=True)
class RoundHealth:
    """Round-health attestation for one discovery pass (R7)."""

    status: str = HEALTH_SUCCESS
    evidence_nonempty: bool = True

    def __post_init__(self) -> None:
        if self.status not in {
            HEALTH_SUCCESS,
            HEALTH_ERROR,
            HEALTH_TRUNCATED,
            HEALTH_RATE_LIMITED,
        }:
            raise ValueError(f"unknown round-health status: {self.status}")

    @property
    def healthy(self) -> bool:
        return self.status == HEALTH_SUCCESS and self.evidence_nonempty

    @property
    def dry_clean_eligible(self) -> bool:
        return self.status == HEALTH_SUCCESS and self.evidence_nonempty


@dataclass(frozen=True)
class DiscoveryRound:
    """One discovery pass with attested health."""

    findings: tuple[Finding, ...] = ()
    health: RoundHealth = field(default_factory=RoundHealth)


@dataclass(frozen=True)
class ConvergenceRound:
    number: int
    observed: int
    new_findings: int
    duplicate_findings: int
    tokens: int
    health_status: str = HEALTH_SUCCESS


@dataclass(frozen=True)
class ConvergenceResult:
    verdict: str
    reason: str
    reason_code: str
    rounds: tuple[ConvergenceRound, ...]
    fingerprints: tuple[str, ...]
    findings_seen: int
    tokens_used: int
    partial: bool = False
    progress_on_prior_findings: tuple[str, ...] = ()
    dry_kind: str | None = None

    @property
    def converged(self) -> bool:
        return self.verdict == "converged"


class FingerprintStore(Protocol):
    """Provider-neutral memory-preflight boundary for fingerprint persistence."""

    def load(self, namespace: str) -> Iterable[str]:
        """Load prior fingerprints through the configured memory-preflight adapter."""

    def save(self, namespace: str, fingerprints: Iterable[str]) -> None:
        """Persist fingerprints through memory-preflight; never persist finding content."""


class MemoryPreflightFingerprintStore:
    """Adapter around memory-preflight read/write operations supplied by the caller."""

    def __init__(
        self,
        load_fingerprints: Callable[[str], Iterable[str]],
        save_fingerprints: Callable[[str, tuple[str, ...]], None],
    ) -> None:
        self._load_fingerprints = load_fingerprints
        self._save_fingerprints = save_fingerprints

    def load(self, namespace: str) -> Iterable[str]:
        return self._load_fingerprints(namespace)

    def save(self, namespace: str, fingerprints: Iterable[str]) -> None:
        self._save_fingerprints(namespace, tuple(sorted(set(fingerprints))))


class InMemoryFingerprintStore:
    """Deterministic fixture store exposing only persisted fingerprints."""

    def __init__(self) -> None:
        self.values: dict[str, tuple[str, ...]] = {}

    def load(self, namespace: str) -> Iterable[str]:
        return self.values.get(namespace, ())

    def save(self, namespace: str, fingerprints: Iterable[str]) -> None:
        self.values[namespace] = tuple(sorted(set(fingerprints)))


def fingerprint_finding(content: Any) -> str:
    """Return a stable SHA-256 fingerprint for JSON-compatible finding content."""
    try:
        canonical = json.dumps(
            content,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"finding content must be JSON-compatible: {exc}") from exc
    return hashlib.sha256(canonical).hexdigest()


Discover = Callable[[int, frozenset[str]], DiscoveryRound | Iterable[Finding]]


def _coerce_discovery(raw: DiscoveryRound | Iterable[Finding]) -> DiscoveryRound:
    if isinstance(raw, DiscoveryRound):
        return raw
    findings = tuple(raw)
    return DiscoveryRound(
        findings=findings,
        health=RoundHealth(
            status=HEALTH_SUCCESS,
            evidence_nonempty=len(findings) > 0,
        ),
    )


def _health_reason_code(health: RoundHealth) -> str:
    if health.status == HEALTH_ERROR:
        return REASON_DISCOVERY_ERROR
    if health.status == HEALTH_TRUNCATED:
        return REASON_TRUNCATED
    if health.status == HEALTH_RATE_LIMITED:
        return REASON_RATE_LIMITED
    return REASON_DRY_ERROR


def _duplicate_rate(round_record: ConvergenceRound) -> float:
    if round_record.observed == 0:
        return 0.0
    return round_record.duplicate_findings / round_record.observed


def _productive_healthy(round_record: ConvergenceRound) -> bool:
    return round_record.health_status == HEALTH_SUCCESS and round_record.new_findings > 0


def _result(
    *,
    verdict: str,
    reason: str,
    reason_code: str,
    rounds: tuple[ConvergenceRound, ...],
    seen: set[str],
    findings_seen: int,
    tokens_used: int,
    partial: bool = False,
    progress_on_prior_findings: tuple[str, ...] = (),
    dry_kind: str | None = None,
) -> ConvergenceResult:
    return ConvergenceResult(
        verdict=verdict,
        reason=reason,
        reason_code=reason_code,
        rounds=rounds,
        fingerprints=tuple(sorted(seen)),
        findings_seen=findings_seen,
        tokens_used=tokens_used,
        partial=partial,
        progress_on_prior_findings=progress_on_prior_findings,
        dry_kind=dry_kind,
    )


def _dry_error_result(
    *,
    reason: str,
    reason_code: str,
    rounds: tuple[ConvergenceRound, ...],
    seen: set[str],
    findings_seen: int,
    tokens_used: int,
) -> ConvergenceResult:
    return _result(
        verdict="failed",
        reason=reason,
        reason_code=reason_code,
        rounds=rounds,
        seen=seen,
        findings_seen=findings_seen,
        tokens_used=tokens_used,
        dry_kind="error",
    )


def _maybe_discretionary_stop(
    *,
    policy: ConvergencePolicy,
    productive_rounds: int,
    round_record: ConvergenceRound,
    duplicate_fingerprints: tuple[str, ...],
    tokens_used: int,
    budgets: ConvergenceBudgets,
    rounds: tuple[ConvergenceRound, ...],
    seen: set[str],
    findings_seen: int,
) -> ConvergenceResult | None:
    if productive_rounds < policy.min_productive_rounds_for_discretionary:
        return None

    dup_rate = _duplicate_rate(round_record)
    if dup_rate >= policy.duplicate_rate_threshold and round_record.observed > 0:
        return _result(
            verdict="converged",
            reason="duplicate-rate discretionary stop",
            reason_code=REASON_DUPLICATE_RATE,
            rounds=rounds,
            seen=seen,
            findings_seen=findings_seen,
            tokens_used=tokens_used,
            progress_on_prior_findings=duplicate_fingerprints,
        )

    if (
        round_record.new_findings <= policy.marginal_value_max_new
        and round_record.duplicate_findings > 0
        and round_record.observed > 0
    ):
        return _result(
            verdict="converged",
            reason="marginal-value discretionary stop",
            reason_code=REASON_MARGINAL_VALUE,
            rounds=rounds,
            seen=seen,
            findings_seen=findings_seen,
            tokens_used=tokens_used,
        )

    soft_cap = int(budgets.max_tokens * policy.token_soft_stop_fraction)
    if tokens_used >= soft_cap and round_record.new_findings == 0:
        return _result(
            verdict="converged",
            reason="token-budget discretionary stop",
            reason_code=REASON_TOKEN_BUDGET,
            rounds=rounds,
            seen=seen,
            findings_seen=findings_seen,
            tokens_used=tokens_used,
        )

    return None


def run_convergence_loop(
    namespace: str,
    discover: Discover,
    *,
    budgets: ConvergenceBudgets,
    fingerprint_store: FingerprintStore,
    policy: ConvergencePolicy | None = None,
) -> ConvergenceResult:
    """Run until dry-clean convergence, discretionary stop, or a declared budget ceiling."""
    active_policy = policy or ConvergencePolicy()
    try:
        loaded = tuple(fingerprint_store.load(namespace))
    except Exception as exc:
        raise ConvergenceError("fingerprint store is unreadable") from exc
    if any(
        not isinstance(item, str)
        or len(item) != 64
        or any(character not in "0123456789abcdef" for character in item)
        for item in loaded
    ):
        raise ConvergenceError("fingerprint store contains invalid data")

    seen = set(loaded)
    rounds: list[ConvergenceRound] = []
    findings_seen = 0
    tokens_used = 0
    productive_rounds = 0

    for number in range(1, budgets.max_rounds + 1):
        discovery = _coerce_discovery(discover(number, frozenset(seen)))
        observed = list(discovery.findings)
        health = discovery.health
        if any(not isinstance(item, Finding) for item in observed):
            raise ConvergenceError("discover must return Finding values")

        if health.status != HEALTH_SUCCESS:
            return _dry_error_result(
                reason=f"discovery {health.status}",
                reason_code=_health_reason_code(health),
                rounds=tuple(rounds),
                seen=seen,
                findings_seen=findings_seen,
                tokens_used=tokens_used,
            )

        round_tokens = sum(item.tokens for item in observed)
        if tokens_used + round_tokens > budgets.max_tokens:
            outstanding = len(observed) > 0 and any(
                fingerprint_finding(item.content) not in seen for item in observed
            )
            return _result(
                verdict="budget-exhausted",
                reason="token budget exhausted with outstanding findings"
                if outstanding
                else "token budget exhausted",
                reason_code=REASON_TOKEN_BUDGET,
                rounds=tuple(rounds),
                seen=seen,
                findings_seen=findings_seen,
                tokens_used=tokens_used,
            )

        fingerprints = [fingerprint_finding(item.content) for item in observed]
        duplicate_fingerprints = tuple(
            item for item in fingerprints if item in seen
        )
        new = [item for item in fingerprints if item not in seen]
        unique_new = tuple(dict.fromkeys(new))
        if findings_seen + len(unique_new) > budgets.max_findings:
            return _result(
                verdict="budget-exhausted",
                reason="finding budget exhausted",
                reason_code=REASON_FINDING_BUDGET,
                rounds=tuple(rounds),
                seen=seen,
                findings_seen=findings_seen,
                tokens_used=tokens_used,
            )

        seen.update(unique_new)
        findings_seen += len(unique_new)
        tokens_used += round_tokens
        round_record = ConvergenceRound(
            number=number,
            observed=len(observed),
            new_findings=len(unique_new),
            duplicate_findings=len(fingerprints) - len(unique_new),
            tokens=round_tokens,
            health_status=health.status,
        )
        rounds.append(round_record)
        if _productive_healthy(round_record):
            productive_rounds += 1

        try:
            fingerprint_store.save(namespace, tuple(sorted(seen)))
        except Exception as exc:
            raise ConvergenceError("fingerprint store write failed") from exc

        if not unique_new:
            has_run_evidence = findings_seen > 0 or round_record.observed > 0
            if health.dry_clean_eligible and has_run_evidence:
                return _result(
                    verdict="converged",
                    reason="dry-clean round",
                    reason_code=REASON_DRY_CLEAN,
                    rounds=tuple(rounds),
                    seen=seen,
                    findings_seen=findings_seen,
                    tokens_used=tokens_used,
                    dry_kind="clean",
                )
            return _dry_error_result(
                reason="dry-error round",
                reason_code=REASON_DRY_ERROR,
                rounds=tuple(rounds),
                seen=seen,
                findings_seen=findings_seen,
                tokens_used=tokens_used,
            )

        discretionary = _maybe_discretionary_stop(
            policy=active_policy,
            productive_rounds=productive_rounds,
            round_record=round_record,
            duplicate_fingerprints=duplicate_fingerprints,
            tokens_used=tokens_used,
            budgets=budgets,
            rounds=tuple(rounds),
            seen=seen,
            findings_seen=findings_seen,
        )
        if discretionary is not None:
            return discretionary

    return _result(
        verdict="halted",
        reason="max rounds exceeded",
        reason_code=REASON_MAX_ROUNDS,
        rounds=tuple(rounds),
        seen=seen,
        findings_seen=findings_seen,
        tokens_used=tokens_used,
        partial=True,
    )


__all__ = [
    "CONVERGENCE_REASON_CODES",
    "ConvergenceBudgets",
    "ConvergenceError",
    "ConvergencePolicy",
    "ConvergenceResult",
    "ConvergenceRound",
    "DiscoveryRound",
    "Finding",
    "FingerprintStore",
    "InMemoryFingerprintStore",
    "MemoryPreflightFingerprintStore",
    "REASON_DISCOVERY_ERROR",
    "REASON_DRY_CLEAN",
    "REASON_DRY_ERROR",
    "REASON_DUPLICATE_RATE",
    "REASON_FINDING_BUDGET",
    "REASON_MARGINAL_VALUE",
    "REASON_MAX_ROUNDS",
    "REASON_RATE_LIMITED",
    "REASON_TOKEN_BUDGET",
    "REASON_TRUNCATED",
    "RoundHealth",
    "Discover",
    "fingerprint_finding",
    "run_convergence_loop",
]
