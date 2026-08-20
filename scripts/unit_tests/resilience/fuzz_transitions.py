#!/usr/bin/env python3
"""Depth/time bounded fuzz driver for resilience transition sequences (PRD 323 R9)."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from unit_tests.resilience.harness import (
    InjectionBoundary,
    InjectionPlan,
    ResilienceHarness,
    TransitionRequest,
    new_fixture_root,
)


DEFAULT_SEED = 323
DEFAULT_MAX_DEPTH = 64
DEFAULT_MAX_SECONDS = 2.0


@dataclass(frozen=True)
class FuzzReport:
    seed: int
    depth: int
    elapsed_seconds: float
    transitions: int
    injected: int
    blocked: int
    passed: int
    sequence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "depth": self.depth,
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "transitions": self.transitions,
            "injected": self.injected,
            "blocked": self.blocked,
            "passed": self.passed,
            "sequence": list(self.sequence),
        }


def _choose_injection(rng: random.Random) -> InjectionPlan:
    boundaries = list(InjectionBoundary)
    count = rng.randint(0, len(boundaries))
    chosen = rng.sample(boundaries, k=count) if count else []
    return InjectionPlan(inject_at=frozenset(chosen))


def fuzz_transitions(
    *,
    seed: int = DEFAULT_SEED,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    root: Path | None = None,
) -> FuzzReport:
    """Exercise random transition sequences under deterministic seed and budgets."""
    rng = random.Random(seed)
    fixture_root = new_fixture_root(root)
    started = time.monotonic()
    sequence: list[str] = []
    injected = blocked = passed = 0
    depth = 0

    for depth in range(1, max_depth + 1):
        if time.monotonic() - started >= max_seconds:
            break
        plan = _choose_injection(rng)
        harness = ResilienceHarness(fixture_root, plan=plan)
        generation = rng.randint(0, 3)
        cache_identity = f"cache-{rng.randint(0, 2)}"
        actor = f"actor-{rng.randint(0, 2)}"
        result = harness.transition(
            TransitionRequest(
                actor=actor,
                generation=generation,
                cache_identity=cache_identity,
            )
        )
        label = result.verdict
        if result.boundary is not None:
            label = f"{result.verdict}:{result.boundary.value}"
        sequence.append(label)
        if result.verdict == "injected":
            injected += 1
        elif result.verdict == "blocked":
            blocked += 1
        else:
            passed += 1
        if rng.random() < 0.35:
            ResilienceHarness(fixture_root).release_lease(actor)

    elapsed = time.monotonic() - started
    return FuzzReport(
        seed=seed,
        depth=depth,
        elapsed_seconds=elapsed,
        transitions=len(sequence),
        injected=injected,
        blocked=blocked,
        passed=passed,
        sequence=tuple(sequence),
    )


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Bounded resilience transition fuzz driver")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH)
    parser.add_argument("--max-seconds", type=float, default=DEFAULT_MAX_SECONDS)
    args = parser.parse_args(argv)
    report = fuzz_transitions(
        seed=args.seed,
        max_depth=args.max_depth,
        max_seconds=args.max_seconds,
    )
    print(report.to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
