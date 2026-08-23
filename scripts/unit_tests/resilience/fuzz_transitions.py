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
from unit_tests.resilience.property_model import (
    PropertyHarness,
    PropertyTransitionKind,
    PropertyTransitionRequest,
    RESIDUAL_TRANSITION_KINDS,
    assurance_non_decreasing,
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


@dataclass(frozen=True)
class FuzzFailureReport:
    seed: int
    depth: int
    elapsed_seconds: float
    cause: str
    sequence: tuple[str, ...]
    shrunkSequence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": "fail",
            "seed": self.seed,
            "depth": self.depth,
            "elapsedSeconds": round(self.elapsed_seconds, 3),
            "cause": self.cause,
            "sequence": list(self.sequence),
            "shrunkSequence": list(self.shrunkSequence),
            "replayable": True,
        }


def _choose_injection(rng: random.Random) -> InjectionPlan:
    boundaries = list(InjectionBoundary)
    count = rng.randint(0, len(boundaries))
    chosen = rng.sample(boundaries, k=count) if count else []
    return InjectionPlan(inject_at=frozenset(chosen))


def _step_label(result_verdict: str, boundary: InjectionBoundary | None, *, kind: str | None = None) -> str:
    label = result_verdict
    if boundary is not None:
        label = f"{result_verdict}:{boundary.value}"
    if kind:
        label = f"{kind}:{label}"
    return label


def _run_sequence(
    *,
    seed: int,
    steps: tuple[str, ...],
    root: Path | None = None,
) -> tuple[tuple[str, ...], str | None]:
    """Replay an encoded step sequence; return labels and optional invariant violation."""
    rng = random.Random(seed)
    fixture_root = new_fixture_root(root)
    labels: list[str] = []
    harness = PropertyHarness(fixture_root)
    assurance_before = harness.property.assurance_level

    for step in steps:
        plan = _choose_injection(rng)
        harness = PropertyHarness(fixture_root, plan=plan)
        generation = rng.randint(0, 3)
        cache_identity = f"cache-{rng.randint(0, 2)}"
        actor = f"actor-{rng.randint(0, 2)}"
        kind = PropertyTransitionKind.STANDARD
        if step.startswith("residual:"):
            kind_name = step.split(":", 1)[1]
            kind = PropertyTransitionKind(kind_name)
        result = harness.transition(
            PropertyTransitionRequest(
                actor=actor,
                generation=generation,
                cache_identity=cache_identity,
                kind=kind,
            )
        )
        label = _step_label(result.verdict, result.boundary, kind=kind.value if kind != PropertyTransitionKind.STANDARD else None)
        labels.append(label)
        assurance_after = harness.property.assurance_level
        if not assurance_non_decreasing(assurance_before, assurance_after):
            return tuple(labels), "assurance-decrease-forbidden"
        assurance_before = assurance_after
        if rng.random() < 0.35:
            ResilienceHarness(fixture_root).release_lease(actor)
    return tuple(labels), None


def shrink_sequence(seed: int, sequence: tuple[str, ...]) -> tuple[str, ...]:
    """Return a minimal subsequence that still reproduces a property failure."""
    if not sequence:
        return sequence
    _, failure = _run_sequence(seed=seed, steps=sequence)
    if failure is None:
        return sequence

    minimal = list(sequence)
    changed = True
    while changed and len(minimal) > 1:
        changed = False
        for index in range(len(minimal)):
            candidate = tuple(minimal[:index] + minimal[index + 1 :])
            _, candidate_failure = _run_sequence(seed=seed, steps=candidate)
            if candidate_failure == failure:
                minimal.pop(index)
                changed = True
                break
    return tuple(minimal)


def replay_fuzz(
    *,
    seed: int,
    sequence: tuple[str, ...],
    root: Path | None = None,
) -> FuzzReport | FuzzFailureReport:
    """Deterministically replay a recorded fuzz sequence under the same seed."""
    started = time.monotonic()
    labels, failure = _run_sequence(seed=seed, steps=sequence, root=root)
    elapsed = time.monotonic() - started
    if failure is not None:
        return FuzzFailureReport(
            seed=seed,
            depth=len(labels),
            elapsed_seconds=elapsed,
            cause=failure,
            sequence=labels,
            shrunkSequence=shrink_sequence(seed, sequence),
        )
    injected = sum(1 for item in labels if item.startswith("injected"))
    blocked = sum(1 for item in labels if item.startswith("blocked"))
    passed = len(labels) - injected - blocked
    return FuzzReport(
        seed=seed,
        depth=len(labels),
        elapsed_seconds=elapsed,
        transitions=len(labels),
        injected=injected,
        blocked=blocked,
        passed=passed,
        sequence=labels,
    )


def fuzz_transitions(
    *,
    seed: int = DEFAULT_SEED,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_seconds: float = DEFAULT_MAX_SECONDS,
    root: Path | None = None,
    include_residuals: bool = False,
) -> FuzzReport | FuzzFailureReport:
    """Exercise random transition sequences under deterministic seed and budgets."""
    rng = random.Random(seed)
    fixture_root = new_fixture_root(root)
    started = time.monotonic()
    sequence: list[str] = []
    encoded_steps: list[str] = []
    injected = blocked = passed = 0
    depth = 0
    harness = PropertyHarness(fixture_root)
    assurance_before = harness.property.assurance_level

    for depth in range(1, max_depth + 1):
        if time.monotonic() - started >= max_seconds:
            break
        plan = _choose_injection(rng)
        harness = PropertyHarness(fixture_root, plan=plan)
        generation = rng.randint(0, 3)
        cache_identity = f"cache-{rng.randint(0, 2)}"
        actor = f"actor-{rng.randint(0, 2)}"
        kind = PropertyTransitionKind.STANDARD
        encoded = "standard"
        if include_residuals and rng.random() < 0.2:
            kind = rng.choice(RESIDUAL_TRANSITION_KINDS)
            encoded = f"residual:{kind.value}"
        result = harness.transition(
            PropertyTransitionRequest(
                actor=actor,
                generation=generation,
                cache_identity=cache_identity,
                kind=kind,
            )
        )
        label = _step_label(result.verdict, result.boundary, kind=kind.value if kind != PropertyTransitionKind.STANDARD else None)
        sequence.append(label)
        encoded_steps.append(encoded)
        if result.verdict == "injected":
            injected += 1
        elif result.verdict == "blocked":
            blocked += 1
        else:
            passed += 1
        assurance_after = harness.property.assurance_level
        if not assurance_non_decreasing(assurance_before, assurance_after):
            elapsed = time.monotonic() - started
            step_tuple = tuple(encoded_steps)
            return FuzzFailureReport(
                seed=seed,
                depth=depth,
                elapsed_seconds=elapsed,
                cause="assurance-decrease-forbidden",
                sequence=tuple(sequence),
                shrunkSequence=shrink_sequence(seed, step_tuple),
            )
        assurance_before = assurance_after
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
    parser.add_argument("--include-residuals", action="store_true")
    parser.add_argument("--replay", nargs="*", default=None, help="Replay encoded step sequence under --seed")
    args = parser.parse_args(argv)
    if args.replay is not None:
        report = replay_fuzz(seed=args.seed, sequence=tuple(args.replay))
    else:
        report = fuzz_transitions(
            seed=args.seed,
            max_depth=args.max_depth,
            max_seconds=args.max_seconds,
            include_residuals=args.include_residuals,
        )
    print(report.to_dict())
    return 0 if isinstance(report, FuzzReport) else 20


if __name__ == "__main__":
    raise SystemExit(main())
