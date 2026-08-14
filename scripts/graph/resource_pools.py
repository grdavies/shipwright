#!/usr/bin/env python3
"""Named concurrency pools with backpressure (PRD 092 R6; PRD 269 R1/R2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PoolName(str, Enum):
    CODE_WRITERS = "code-writers"
    READ_ONLY_REVIEWERS = "read-only-reviewers"
    WEB_RESEARCH = "web-research"
    PROVIDER_API = "provider-api"


DEFAULT_LIMITS: dict[PoolName, int] = {
    PoolName.CODE_WRITERS: 4,
    PoolName.READ_ONLY_REVIEWERS: 8,
    PoolName.WEB_RESEARCH: 4,
    PoolName.PROVIDER_API: 4,
}


class PoolExhausted(RuntimeError):
    """Raised when acquire would exceed the configured limit (backpressure / park)."""

    def __init__(self, pool: PoolName, limit: int, in_use: int, *, slots: int = 1) -> None:
        super().__init__(
            f"pool exhausted: {pool.value} in_use={in_use} limit={limit} slots={slots}"
        )
        self.pool = pool
        self.limit = limit
        self.in_use = in_use
        self.slots = slots


class PoolRequestUnsatisfiable(ValueError):
    """Raised when requested slots exceed the pool limit (never parkable)."""

    def __init__(self, pool: PoolName, limit: int, slots: int) -> None:
        super().__init__(
            f"pool request unsatisfiable: {pool.value} slots={slots} exceed limit={limit}"
        )
        self.pool = pool
        self.limit = limit
        self.slots = slots


@dataclass
class PoolState:
    limit: int
    in_use: int = 0
    waiters: int = 0

    def available(self) -> int:
        return max(0, self.limit - self.in_use)


@dataclass
class ResourcePoolRegistry:
    """In-process registry. Hard ceiling may not exceed ``hard_ceiling`` (harness bound)."""

    hard_ceiling: int = 16
    pools: dict[PoolName, PoolState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.pools:
            self.pools = {
                name: PoolState(limit=min(limit, self.hard_ceiling))
                for name, limit in DEFAULT_LIMITS.items()
            }
        else:
            for state in self.pools.values():
                if state.limit > self.hard_ceiling:
                    raise ValueError(
                        f"pool limit {state.limit} exceeds hard ceiling {self.hard_ceiling}"
                    )

    @classmethod
    def from_config(
        cls,
        *,
        limits: dict[str, int] | None = None,
        hard_ceiling: int = 16,
    ) -> ResourcePoolRegistry:
        pools: dict[PoolName, PoolState] = {}
        for name in PoolName:
            raw = (limits or {}).get(name.value, DEFAULT_LIMITS[name])
            limit = min(int(raw), hard_ceiling)
            pools[name] = PoolState(limit=limit)
        return cls(hard_ceiling=hard_ceiling, pools=pools)

    def can_satisfy(self, pool: PoolName, *, slots: int = 1) -> bool:
        """True when the request can ever succeed (slots ≤ limit), regardless of in-use."""
        if slots < 1:
            raise ValueError("slots must be >= 1")
        return slots <= self.pools[pool].limit

    def acquire(self, pool: PoolName, *, slots: int = 1) -> None:
        if slots < 1:
            raise ValueError("slots must be >= 1")
        state = self.pools[pool]
        if slots > state.limit:
            raise PoolRequestUnsatisfiable(pool, state.limit, slots)
        if state.in_use + slots > state.limit:
            state.waiters += 1
            raise PoolExhausted(pool, state.limit, state.in_use, slots=slots)
        state.in_use += slots

    def release(self, pool: PoolName, *, slots: int = 1) -> None:
        if slots < 1:
            raise ValueError("slots must be >= 1")
        state = self.pools[pool]
        state.in_use = max(0, state.in_use - slots)
        if state.waiters:
            state.waiters = max(0, state.waiters - 1)

    def snapshot(self) -> dict[str, Any]:
        return {
            name.value: {
                "limit": state.limit,
                "inUse": state.in_use,
                "available": state.available(),
                "waiters": state.waiters,
            }
            for name, state in self.pools.items()
        }
