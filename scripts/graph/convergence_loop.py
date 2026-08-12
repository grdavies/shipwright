#!/usr/bin/env python3
"""Bounded loop-until-dry execution with fingerprint-only persistence."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol


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
class Finding:
    """One discovery. Content remains transient; only its fingerprint persists."""

    content: Any
    tokens: int = 0

    def __post_init__(self) -> None:
        if isinstance(self.tokens, bool) or not isinstance(self.tokens, int) or self.tokens < 0:
            raise ValueError("finding tokens must be a non-negative integer")


@dataclass(frozen=True)
class ConvergenceRound:
    number: int
    observed: int
    new_findings: int
    duplicate_findings: int
    tokens: int


@dataclass(frozen=True)
class ConvergenceResult:
    verdict: str
    reason: str
    rounds: tuple[ConvergenceRound, ...]
    fingerprints: tuple[str, ...]
    findings_seen: int
    tokens_used: int

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


Discover = Callable[[int, frozenset[str]], Iterable[Finding]]


def run_convergence_loop(
    namespace: str,
    discover: Discover,
    *,
    budgets: ConvergenceBudgets,
    fingerprint_store: FingerprintStore,
) -> ConvergenceResult:
    """Run until a dry round or a declared budget is exhausted."""
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

    for number in range(1, budgets.max_rounds + 1):
        observed = list(discover(number, frozenset(seen)))
        if any(not isinstance(item, Finding) for item in observed):
            raise ConvergenceError("discover must return Finding values")
        round_tokens = sum(item.tokens for item in observed)
        if tokens_used + round_tokens > budgets.max_tokens:
            return ConvergenceResult(
                "budget-exhausted",
                "token budget exhausted",
                tuple(rounds),
                tuple(sorted(seen)),
                findings_seen,
                tokens_used,
            )

        fingerprints = [fingerprint_finding(item.content) for item in observed]
        new = [item for item in fingerprints if item not in seen]
        unique_new = tuple(dict.fromkeys(new))
        if findings_seen + len(unique_new) > budgets.max_findings:
            return ConvergenceResult(
                "budget-exhausted",
                "finding budget exhausted",
                tuple(rounds),
                tuple(sorted(seen)),
                findings_seen,
                tokens_used,
            )

        seen.update(unique_new)
        findings_seen += len(unique_new)
        tokens_used += round_tokens
        rounds.append(
            ConvergenceRound(
                number=number,
                observed=len(observed),
                new_findings=len(unique_new),
                duplicate_findings=len(fingerprints) - len(unique_new),
                tokens=round_tokens,
            )
        )
        try:
            fingerprint_store.save(namespace, tuple(sorted(seen)))
        except Exception as exc:
            raise ConvergenceError("fingerprint store write failed") from exc
        if not unique_new:
            return ConvergenceResult(
                "converged",
                "dry round",
                tuple(rounds),
                tuple(sorted(seen)),
                findings_seen,
                tokens_used,
            )

    return ConvergenceResult(
        "budget-exhausted",
        "round budget exhausted",
        tuple(rounds),
        tuple(sorted(seen)),
        findings_seen,
        tokens_used,
    )
