#!/usr/bin/env python3
"""Phased, dogfood-gated cutover from legacy plans to the graph scheduler."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from graph.legacy_adapters import compile_legacy_plan
from graph.scheduler import GraphScheduler, SchedulerRun
from graph.scheduling_modes import SchedulingMode, validate_scheduling_mode
from graph.verifier_policies import VerifierKind, VerifierResult, evaluate_verifiers


class CutoverError(RuntimeError):
    """Base class for cutover safety failures."""


class CoverageLossError(CutoverError):
    """Raised when graph compilation or execution loses a legacy step."""


class CutoverStage(str, Enum):
    DOGFOOD = "dogfood"
    LIMITED = "limited-scope"
    FULL = "full-ownership"


@dataclass(frozen=True)
class DogfoodEvidence:
    completed_runs: int
    parity_passed: bool
    coverage_complete: bool
    verification_passed: bool

    @classmethod
    def passing(cls, *, completed_runs: int) -> DogfoodEvidence:
        return cls(
            completed_runs=completed_runs,
            parity_passed=True,
            coverage_complete=True,
            verification_passed=True,
        )

    @property
    def passed(self) -> bool:
        return (
            self.completed_runs > 0
            and self.parity_passed
            and self.coverage_complete
            and self.verification_passed
        )


@dataclass(frozen=True)
class SafetySnapshot:
    """Legacy-owned orchestration state that cutover must not reinterpret."""

    lock_owner: str
    merge_queue: tuple[str, ...]
    contention_serialized: tuple[str, ...]
    resume_cursor: str
    human_merge_gate: bool

    @classmethod
    def from_plan(cls, plan: Mapping[str, Any]) -> SafetySnapshot:
        raw = plan.get("safety")
        if not isinstance(raw, Mapping):
            raise CutoverError("cutover requires a legacy safety envelope")
        snapshot = cls(
            lock_owner=str(raw.get("lockOwner") or ""),
            merge_queue=tuple(str(item) for item in raw.get("mergeQueue") or ()),
            contention_serialized=tuple(
                str(item) for item in raw.get("contentionSerialized") or ()
            ),
            resume_cursor=str(raw.get("resumeCursor") or ""),
            human_merge_gate=raw.get("humanMergeGate") is True,
        )
        if not snapshot.lock_owner or not snapshot.resume_cursor:
            raise CutoverError("cutover safety envelope is missing lock or resume state")
        if not snapshot.human_merge_gate:
            raise CutoverError("cutover cannot remove the human merge gate")
        return snapshot


@dataclass(frozen=True)
class CutoverRun:
    path: str
    steps: tuple[str, ...]
    safety: SafetySnapshot
    verdict: str
    scheduler_run: SchedulerRun | None = None


@dataclass(frozen=True)
class ParityVerdict:
    passed: bool
    coverage_complete: bool
    safety_unchanged: bool
    reason: str


def _legacy_steps(plan: Mapping[str, Any], plan_type: str) -> tuple[str, ...]:
    if plan_type == "delivery":
        phases = plan.get("phases")
        if not isinstance(phases, list):
            raise CutoverError("delivery plan has no phases")
        return tuple(
            str(phase.get("slug") or phase.get("name") or phase.get("id"))
            for phase in phases
            if isinstance(phase, Mapping)
        )
    raw_steps = plan.get("steps")
    if not isinstance(raw_steps, list):
        raise CutoverError(f"{plan_type} plan has no steps")
    return tuple(
        str(step.get("command") or step.get("name") or step.get("id"))
        if isinstance(step, Mapping)
        else str(step)
        for step in raw_steps
    )


def _graph_steps(graph: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(node["target"]["step"]) for node in graph["spec"]["nodes"])


class CutoverDriver:
    """Route eligible runs through phased cutover without owning legacy safety state."""

    def __init__(self, *, stage: CutoverStage = CutoverStage.DOGFOOD) -> None:
        self.stage = stage

    def promote(self, evidence: DogfoodEvidence) -> CutoverStage:
        required_runs = 1 if self.stage is CutoverStage.DOGFOOD else 3
        if not evidence.passed or evidence.completed_runs < required_runs:
            raise PermissionError(
                f"dogfood gate failed for {self.stage.value}: "
                f"need {required_runs} passing run(s)"
            )
        if self.stage is CutoverStage.DOGFOOD:
            self.stage = CutoverStage.LIMITED
        elif self.stage is CutoverStage.LIMITED:
            self.stage = CutoverStage.FULL
        return self.stage

    def _assert_route_allowed(
        self,
        *,
        non_merge_critical: bool,
        limited_scope: bool,
    ) -> None:
        if self.stage is CutoverStage.DOGFOOD and not non_merge_critical:
            raise PermissionError("dogfood cutover accepts non-merge-critical runs only")
        if (
            self.stage is CutoverStage.LIMITED
            and not non_merge_critical
            and not limited_scope
        ):
            raise PermissionError("limited cutover requires an explicitly limited scope")

    @staticmethod
    def run_legacy(
        plan: Mapping[str, Any],
        *,
        plan_type: str,
        safety: SafetySnapshot,
        executor: Callable[[str], str],
    ) -> CutoverRun:
        """Execute the legacy path and record its observable parity baseline."""
        steps = _legacy_steps(plan, plan_type)
        verdict = "pass"
        for step in steps:
            if executor(step) != "pass":
                verdict = "fail"
                break
        return CutoverRun(
            path="legacy",
            steps=steps,
            safety=safety,
            verdict=verdict,
        )

    def run_scheduler(
        self,
        plan: Mapping[str, Any],
        *,
        plan_type: str,
        run_id: str,
        scheduler: GraphScheduler,
        safety: SafetySnapshot,
        non_merge_critical: bool = False,
        limited_scope: bool = False,
        graph_transform: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> CutoverRun:
        """Compile and execute an eligible legacy plan through WorkflowGraph."""
        self._assert_route_allowed(
            non_merge_critical=non_merge_critical,
            limited_scope=limited_scope,
        )
        if "safety" in plan and safety != SafetySnapshot.from_plan(plan):
            raise CutoverError("cutover safety state differs from the legacy plan")
        compilation = compile_legacy_plan(plan, plan_type=plan_type)
        graph = compilation.graph
        if graph_transform is not None:
            graph = graph_transform(graph)
        expected = _legacy_steps(plan, plan_type)
        actual = _graph_steps(graph)
        if actual != expected:
            raise CoverageLossError(
                f"coverage loss before scheduler dispatch: "
                f"expected={expected!r} actual={actual!r}"
            )
        for node in graph["spec"]["nodes"]:
            default_mode = (
                SchedulingMode.BARRIER
                if node["kind"] == "barrier"
                else SchedulingMode.PIPELINE
            )
            validate_scheduling_mode(str(node["kind"]), default_mode)

        result = scheduler.run(graph, run_id=run_id, internal_only=True)
        verification = evaluate_verifiers(
            [
                VerifierResult(
                    verifier_id="cutover-scheduler",
                    kind=VerifierKind.MECHANICAL,
                    passed=result.verdict == "pass",
                    evidence_ref=run_id,
                )
            ]
        )
        if not verification.passed:
            raise CutoverError(verification.reason)

        return CutoverRun(
            path="scheduler",
            steps=actual,
            safety=safety,
            verdict=result.verdict,
            scheduler_run=result,
        )

    @staticmethod
    def compare(legacy: CutoverRun, cutover: CutoverRun) -> ParityVerdict:
        coverage_complete = legacy.steps == cutover.steps
        safety_unchanged = legacy.safety == cutover.safety
        passed = (
            legacy.verdict == cutover.verdict == "pass"
            and coverage_complete
            and safety_unchanged
        )
        reasons = []
        if not coverage_complete:
            reasons.append("coverage differs")
        if not safety_unchanged:
            reasons.append("legacy safety state changed")
        if legacy.verdict != cutover.verdict:
            reasons.append("verdict differs")
        elif legacy.verdict != "pass":
            reasons.append(f"both paths returned {legacy.verdict}")
        return ParityVerdict(
            passed=passed,
            coverage_complete=coverage_complete,
            safety_unchanged=safety_unchanged,
            reason=", ".join(reasons) if reasons else "legacy and scheduler paths match",
        )
