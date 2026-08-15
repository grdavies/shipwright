#!/usr/bin/env python3
"""Phased, dogfood-gated cutover from legacy plans to the graph scheduler."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from graph.legacy_adapters import compile_legacy_plan
from graph.observability import READ_ONLY_COMMANDS
from graph.scheduler import GraphScheduler, SchedulerRun
from graph.scheduling_modes import (
    ALLOWED_EXTERNAL_AUTHORIZERS,
    PromotionMetrics,
    RegressionBudget,
    SchedulingMode,
    validate_scheduling_mode,
)
from graph.verifier_policies import VerifierKind, VerifierResult, evaluate_verifiers


class CutoverError(RuntimeError):
    """Base class for cutover safety failures."""


class CoverageLossError(CutoverError):
    """Raised when graph compilation or execution loses a legacy step."""


class CutoverStage(str, Enum):
    DOGFOOD = "dogfood"
    LIMITED = "limited-scope"
    FULL = "full-ownership"


PLAN_POLICY_CANONICAL = "canonical"
PLAN_POLICY_PROPOSED = "proposed"


def status_explain_is_live() -> bool:
    """Return True when the read-only status/explain command surface is available."""
    return "status" in READ_ONLY_COMMANDS and "explain" in READ_ONLY_COMMANDS


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
class PromotionEvidence:
    """Recorded promotion gate evidence for dogfood → limited → full ownership."""

    from_stage: CutoverStage
    to_stage: CutoverStage
    dogfood: DogfoodEvidence
    status_explain_live: bool
    metrics: PromotionMetrics | None = None
    authorizer: str | None = None
    evidence_ref: str | None = None


@dataclass(frozen=True)
class IntegrityScopedInputs:
    """Receipts and calibration tables verified before authorization."""

    receipts_digest: str
    calibration_digest: str


@dataclass(frozen=True)
class DemotionRegression:
    """Defined regressions that demote proposed plan policy back to canonical."""

    prediction_error_exceeded: bool = False
    required_capability_regression: bool = False
    human_rework: bool = False
    metrics_exceeded_budget: bool = False
    receipts_digest_mismatch: bool = False
    calibration_digest_mismatch: bool = False

    @property
    def triggered(self) -> bool:
        return any(
            (
                self.prediction_error_exceeded,
                self.required_capability_regression,
                self.human_rework,
                self.metrics_exceeded_budget,
                self.receipts_digest_mismatch,
                self.calibration_digest_mismatch,
            )
        )

    def reasons(self) -> tuple[str, ...]:
        mapping = {
            "prediction_error_exceeded": self.prediction_error_exceeded,
            "required_capability_regression": self.required_capability_regression,
            "human_rework": self.human_rework,
            "metrics_exceeded_budget": self.metrics_exceeded_budget,
            "receipts_digest_mismatch": self.receipts_digest_mismatch,
            "calibration_digest_mismatch": self.calibration_digest_mismatch,
        }
        return tuple(name for name, active in mapping.items() if active)


@dataclass
class InRunKillSwitch:
    """Operator kill switch that takes effect within the active run."""

    active: bool = False
    activated_by: str = ""
    activated_at: str = ""

    def activate(self, *, actor: str, activated_at: str) -> None:
        if not actor.strip():
            raise CutoverError("kill switch actor is required")
        self.active = True
        self.activated_by = actor.strip()
        self.activated_at = activated_at


@dataclass(frozen=True)
class DemotionRecord:
    plan_policy: str
    reasons: tuple[str, ...]
    actor: str
    demoted_at: str


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
        return cls.from_safety_mapping(raw)

    @classmethod
    def from_safety_mapping(cls, raw: Mapping[str, Any]) -> SafetySnapshot:
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


def assert_human_merge_gate_compiles(plan: Mapping[str, Any]) -> None:
    """Reject plans that attempt to compile with humanMergeGate disabled (R4)."""
    raw = plan.get("safety")
    if not isinstance(raw, Mapping):
        return
    if raw.get("humanMergeGate") is False:
        raise CutoverError("cutover cannot remove the human merge gate")


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
        self.promotion_evidence: list[PromotionEvidence] = []
        self.demotion_records: list[DemotionRecord] = []
        self.plan_policy = PLAN_POLICY_CANONICAL
        self.kill_switch = InRunKillSwitch()

    def activate_kill_switch(self, *, actor: str, activated_at: str) -> InRunKillSwitch:
        """Honor an in-run operator kill switch that takes effect within the run."""
        self.kill_switch.activate(actor=actor, activated_at=activated_at)
        self.plan_policy = PLAN_POLICY_CANONICAL
        return self.kill_switch

    def effective_plan_policy(self) -> str:
        if self.kill_switch.active:
            return PLAN_POLICY_CANONICAL
        return self.plan_policy

    @staticmethod
    def verify_integrity_scoped_inputs(
        *,
        observed_receipts_digest: str,
        observed_calibration_digest: str,
        authorization: IntegrityScopedInputs,
    ) -> bool:
        return (
            observed_receipts_digest == authorization.receipts_digest
            and observed_calibration_digest == authorization.calibration_digest
        )

    def demote_on_regression(
        self,
        regression: DemotionRegression,
        *,
        actor: str,
        demoted_at: str,
        integrity: IntegrityScopedInputs | None = None,
        observed_receipts_digest: str | None = None,
        observed_calibration_digest: str | None = None,
        metrics: PromotionMetrics | None = None,
        budget: RegressionBudget | None = None,
    ) -> DemotionRecord:
        """Demote proposed plan policy to canonical on defined regressions."""
        if not actor.strip():
            raise CutoverError("demotion actor is required")
        combined = DemotionRegression(
            prediction_error_exceeded=regression.prediction_error_exceeded,
            required_capability_regression=regression.required_capability_regression,
            human_rework=regression.human_rework,
            metrics_exceeded_budget=(
                regression.metrics_exceeded_budget
                or (
                    metrics is not None
                    and budget is not None
                    and not metrics.within_budget(budget)
                )
            ),
            receipts_digest_mismatch=regression.receipts_digest_mismatch,
            calibration_digest_mismatch=regression.calibration_digest_mismatch,
        )
        if integrity is not None:
            if observed_receipts_digest is None or observed_calibration_digest is None:
                raise CutoverError(
                    "integrity-scoped demotion requires observed digests"
                )
            if not self.verify_integrity_scoped_inputs(
                observed_receipts_digest=observed_receipts_digest,
                observed_calibration_digest=observed_calibration_digest,
                authorization=integrity,
            ):
                combined = DemotionRegression(
                    prediction_error_exceeded=combined.prediction_error_exceeded,
                    required_capability_regression=combined.required_capability_regression,
                    human_rework=combined.human_rework,
                    metrics_exceeded_budget=combined.metrics_exceeded_budget,
                    receipts_digest_mismatch=True,
                    calibration_digest_mismatch=True,
                )
        if not combined.triggered:
            raise CutoverError("demotion requires a defined regression")
        record = DemotionRecord(
            plan_policy=PLAN_POLICY_CANONICAL,
            reasons=combined.reasons(),
            actor=actor.strip(),
            demoted_at=demoted_at,
        )
        self.plan_policy = PLAN_POLICY_CANONICAL
        self.demotion_records.append(record)
        return record

    def promote_plan_policy(
        self,
        *,
        target_policy: str,
        authorizer: str,
        promoted_at: str,
    ) -> str:
        if target_policy not in {PLAN_POLICY_PROPOSED, PLAN_POLICY_CANONICAL}:
            raise CutoverError(f"unsupported plan policy target: {target_policy}")
        if self.kill_switch.active:
            raise PermissionError("kill switch active; proposed plan policy refused")
        if target_policy == PLAN_POLICY_CANONICAL and self.plan_policy != PLAN_POLICY_PROPOSED:
            raise PermissionError("canonical promotion requires proposed stage")
        if not authorizer.strip():
            raise PermissionError("plan policy promotion requires named authorizer")
        if authorizer not in ALLOWED_EXTERNAL_AUTHORIZERS:
            raise PermissionError(f"unrecognized plan policy authorizer: {authorizer}")
        self.plan_policy = target_policy
        return self.plan_policy

    def promote(
        self,
        evidence: DogfoodEvidence,
        *,
        metrics: PromotionMetrics | None = None,
        authorizer: str | None = None,
        evidence_ref: str | None = None,
    ) -> CutoverStage:
        required_runs = 1 if self.stage is CutoverStage.DOGFOOD else 3
        if not evidence.passed or evidence.completed_runs < required_runs:
            raise PermissionError(
                f"dogfood gate failed for {self.stage.value}: "
                f"need {required_runs} passing run(s)"
            )
        live = status_explain_is_live()
        if self.stage is CutoverStage.DOGFOOD:
            if not live:
                raise PermissionError(
                    "limited-scope promotion requires status/explain live"
                )
            next_stage = CutoverStage.LIMITED
        elif self.stage is CutoverStage.LIMITED:
            if not authorizer or not evidence_ref:
                raise PermissionError(
                    "full-ownership promotion requires named authorizer and evidence"
                )
            if authorizer not in ALLOWED_EXTERNAL_AUTHORIZERS:
                raise PermissionError(f"unrecognized cutover authorizer: {authorizer}")
            next_stage = CutoverStage.FULL
        else:
            raise PermissionError("cutover already at full ownership")
        self.promotion_evidence.append(
            PromotionEvidence(
                from_stage=self.stage,
                to_stage=next_stage,
                dogfood=evidence,
                status_explain_live=live,
                metrics=metrics,
                authorizer=authorizer,
                evidence_ref=evidence_ref,
            )
        )
        self.stage = next_stage
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
        assert_human_merge_gate_compiles(plan)
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
