#!/usr/bin/env python3
"""Hermetic fault-injection harness for deliver resilience boundaries (PRD 323 R7, R9, R24)."""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class InjectionBoundary(str, Enum):
    ADMISSION = "admission"
    LEASE = "lease"
    CACHE = "cache"
    FINALIZE = "finalize"


BOUNDARY_ORDER: tuple[InjectionBoundary, ...] = (
    InjectionBoundary.ADMISSION,
    InjectionBoundary.LEASE,
    InjectionBoundary.CACHE,
    InjectionBoundary.FINALIZE,
)


class InjectedFailure(RuntimeError):
    """Intentional fixture failure at a declared injection boundary."""

    def __init__(self, boundary: InjectionBoundary, message: str = "") -> None:
        self.boundary = boundary
        super().__init__(message or f"injected-failure:{boundary.value}")


@dataclass(frozen=True)
class InjectionPlan:
    """Configure injectable failures per boundary."""

    inject_at: frozenset[InjectionBoundary] = frozenset()

    @classmethod
    def from_names(cls, names: list[str] | tuple[str, ...]) -> InjectionPlan:
        return cls(inject_at=frozenset(InjectionBoundary(name) for name in names))


@dataclass
class InjectionJournal:
    """Observable record of boundary reach and injection firings."""

    reached: list[InjectionBoundary] = field(default_factory=list)
    fired: list[InjectionBoundary] = field(default_factory=list)

    def record_reached(self, boundary: InjectionBoundary) -> None:
        self.reached.append(boundary)

    def record_fired(self, boundary: InjectionBoundary) -> None:
        self.fired.append(boundary)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reached": [item.value for item in self.reached],
            "fired": [item.value for item in self.fired],
        }


@dataclass
class HermeticFixture:
    """Minimal durable state machine with admission/lease/cache/finalize gates."""

    root: Path
    generation: int = 0
    lease_holder: str | None = None
    cache_identity: str = ""
    finalized: bool = False

    @property
    def state_path(self) -> Path:
        return self.root / ".cursor" / "resilience-fixture" / "state.json"

    def load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {
                "generation": 0,
                "leaseHolder": None,
                "cacheIdentity": "",
                "finalized": False,
            }
        payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("fixture state corrupt")
        return payload

    def save(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".state.",
            dir=str(self.state_path.parent),
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

    def sync_from_disk(self) -> None:
        payload = self.load()
        self.generation = int(payload.get("generation") or 0)
        self.lease_holder = payload.get("leaseHolder")
        self.cache_identity = str(payload.get("cacheIdentity") or "")
        self.finalized = bool(payload.get("finalized"))


@dataclass(frozen=True)
class TransitionRequest:
    actor: str
    generation: int
    cache_identity: str
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class TransitionResult:
    verdict: str
    boundary: InjectionBoundary | None = None
    journal: dict[str, Any] | None = None
    cause: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"verdict": self.verdict}
        if self.boundary is not None:
            payload["boundary"] = self.boundary.value
        if self.journal is not None:
            payload["journal"] = self.journal
        if self.cause is not None:
            payload["cause"] = self.cause
        return payload


class ResilienceHarness:
    """Drive hermetic transitions and inject failures at durable boundaries."""

    def __init__(
        self,
        root: Path,
        *,
        plan: InjectionPlan | None = None,
        journal: InjectionJournal | None = None,
    ) -> None:
        self.root = root
        self.plan = plan or InjectionPlan()
        self.journal = journal or InjectionJournal()
        self.fixture = HermeticFixture(root)

    def _maybe_inject(self, boundary: InjectionBoundary) -> None:
        self.journal.record_reached(boundary)
        if boundary not in self.plan.inject_at:
            return
        self.journal.record_fired(boundary)
        raise InjectedFailure(boundary)

    def transition(self, request: TransitionRequest) -> TransitionResult:
        self.fixture.sync_from_disk()
        try:
            self._maybe_inject(InjectionBoundary.ADMISSION)
            if request.generation < self.fixture.generation:
                return TransitionResult(
                    verdict="blocked",
                    boundary=InjectionBoundary.ADMISSION,
                    cause="stale-generation",
                    journal=self.journal.to_dict(),
                )
            if self.fixture.finalized:
                return TransitionResult(
                    verdict="blocked",
                    boundary=InjectionBoundary.ADMISSION,
                    cause="already-finalized",
                    journal=self.journal.to_dict(),
                )

            self._maybe_inject(InjectionBoundary.LEASE)
            if self.fixture.lease_holder not in (None, request.actor):
                return TransitionResult(
                    verdict="blocked",
                    boundary=InjectionBoundary.LEASE,
                    cause="lease-held",
                    journal=self.journal.to_dict(),
                )
            self.fixture.lease_holder = request.actor

            self._maybe_inject(InjectionBoundary.CACHE)
            if request.cache_identity != self.fixture.cache_identity:
                if self.fixture.cache_identity and request.cache_identity != self.fixture.cache_identity:
                    return TransitionResult(
                        verdict="blocked",
                        boundary=InjectionBoundary.CACHE,
                        cause="cache-identity-mismatch",
                        journal=self.journal.to_dict(),
                    )
                self.fixture.cache_identity = request.cache_identity

            self._maybe_inject(InjectionBoundary.FINALIZE)
            payload = {
                "generation": request.generation,
                "leaseHolder": request.actor,
                "cacheIdentity": request.cache_identity,
                "finalized": True,
                "runId": request.run_id,
            }
            self.fixture.save(payload)
            self.fixture.sync_from_disk()
            return TransitionResult(
                verdict="pass",
                journal=self.journal.to_dict(),
            )
        except InjectedFailure as exc:
            return TransitionResult(
                verdict="injected",
                boundary=exc.boundary,
                cause=str(exc),
                journal=self.journal.to_dict(),
            )

    def release_lease(self, actor: str) -> None:
        self.fixture.sync_from_disk()
        if self.fixture.lease_holder == actor:
            self.fixture.lease_holder = None
            payload = self.fixture.load()
            payload["leaseHolder"] = None
            self.fixture.save(payload)


def new_fixture_root(parent: Path | None = None) -> Path:
    """Create an isolated temp root for hermetic harness runs."""
    base = parent or Path(tempfile.gettempdir())
    path = base / f"resilience-fixture-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    (path / ".cursor").mkdir(parents=True, exist_ok=True)
    return path
