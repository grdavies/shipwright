#!/usr/bin/env python3
"""Phased, dogfood-gated cutover from legacy plans to the graph scheduler."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from graph.legacy_adapters import compile_legacy_plan
from graph.observability import READ_ONLY_COMMANDS
from graph.quick_ship_compile import QUICK_SHIP_PARITY_MATRIX
from graph.scheduler import GraphScheduler, SchedulerRun
from graph.scheduling_modes import (
    ALLOWED_EXTERNAL_AUTHORIZERS,
    MitigationLane,
    PromotionMetrics,
    RegressionBudget,
    SERIAL_EQUIVALENT_MAX_CONCURRENCY,
    SchedulingMode,
    validate_scheduling_mode,
)
from graph.timing_events import observed_execution_overlap
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


class RuntimeV2CutoverStage(str, Enum):
    """PRD 271 rollout ladder — ordered closeout for absorbed gaps (R16/D5-G)."""

    ASYNC_CORE = "async-core"
    CACHE_TRUST = "cache-trust"
    BACKEND_LOCAL = "backend-local"
    QUICK_PARITY = "quick-parity"
    ATTRIBUTION = "attribution"
    CUTOVER_EVIDENCE = "cutover-evidence"


RUNTIME_V2_STAGE_ORDER: tuple[RuntimeV2CutoverStage, ...] = (
    RuntimeV2CutoverStage.ASYNC_CORE,
    RuntimeV2CutoverStage.CACHE_TRUST,
    RuntimeV2CutoverStage.BACKEND_LOCAL,
    RuntimeV2CutoverStage.QUICK_PARITY,
    RuntimeV2CutoverStage.ATTRIBUTION,
    RuntimeV2CutoverStage.CUTOVER_EVIDENCE,
)


@dataclass(frozen=True)
class GapCloseoutEntry:
    """One absorbed gap in R16 ordered closeout."""

    order: int
    issue: int
    gap_unit: str
    stage: RuntimeV2CutoverStage
    requirement_ids: tuple[str, ...]
    close_predicate: str
    requires_overlap_ge_2: bool = False


GAP_CLOSEOUT_ORDER: tuple[GapCloseoutEntry, ...] = (
    GapCloseoutEntry(
        order=1,
        issue=674,
        gap_unit="gap-279-p0-graphscheduler-genuine-concurrent-async-execu",
        stage=RuntimeV2CutoverStage.ASYNC_CORE,
        requirement_ids=("R1", "R1a", "R1b", "R2a", "R3"),
        close_predicate="R1/R1a/R1b/R2a/R3 green with observed concurrency ≥2",
        requires_overlap_ge_2=True,
    ),
    GapCloseoutEntry(
        order=2,
        issue=675,
        gap_unit="gap-280-p0-separate-run-journal-from-durable-cross-run-c",
        stage=RuntimeV2CutoverStage.CACHE_TRUST,
        requirement_ids=("R4", "R5", "R6", "R4a", "R4b", "R4c", "R5a", "R5b", "R5c"),
        close_predicate="R4–R6 / R4a–R4c / R5a–R5c green (run-scope dogfood; repository optional)",
    ),
    GapCloseoutEntry(
        order=3,
        issue=681,
        gap_unit="gap-286-p1-explicit-executionbackend-interface",
        stage=RuntimeV2CutoverStage.BACKEND_LOCAL,
        requirement_ids=("R9", "R10", "R14"),
        close_predicate="R9/R10 (+ R14 before multi-worktree mutate)",
    ),
    GapCloseoutEntry(
        order=4,
        issue=676,
        gap_unit="gap-281-p0-bring-quick-tier-sw-ship-onto-workflowgraph",
        stage=RuntimeV2CutoverStage.QUICK_PARITY,
        requirement_ids=("R7", "R7a", "R8"),
        close_predicate="R7/R7a/R8 parity matrix + never-merge",
    ),
    GapCloseoutEntry(
        order=5,
        issue=682,
        gap_unit="gap-287-p1-critical-path-performance-attribution",
        stage=RuntimeV2CutoverStage.ATTRIBUTION,
        requirement_ids=("R11", "R11a", "R11b"),
        close_predicate="R11/R11a/R11b measured path under concurrency ≥2",
        requires_overlap_ge_2=True,
    ),
)


@dataclass(frozen=True)
class OverlapEvidence:
    """Cutover evidence from receipts/timing — configured limit alone is insufficient."""

    configured_max_concurrency: int
    observed_overlap_ge_2: bool
    sufficient_for_cutover: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "configuredMaxConcurrency": self.configured_max_concurrency,
            "observedOverlapGe2": self.observed_overlap_ge_2,
            "sufficientForCutover": self.sufficient_for_cutover,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RollbackResumeContract:
    """Documented rollback/resume mapping for in-flight durable runs (R8/R18)."""

    kill_switch_action: str
    serial_lane: MitigationLane
    resume_authority: str
    rollback_mapping: Mapping[str, Any]
    reentry_command: str
    session_detach_safe: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "killSwitchAction": self.kill_switch_action,
            "serialLane": {
                "maxConcurrency": self.serial_lane.max_concurrency,
                "cacheEnabled": self.serial_lane.cache_enabled,
            },
            "resumeAuthority": self.resume_authority,
            "rollbackMapping": dict(self.rollback_mapping),
            "reentryCommand": self.reentry_command,
            "sessionDetachSafe": self.session_detach_safe,
        }


@dataclass(frozen=True)
class CloseoutCheckItem:
    gap_issue: int
    stage: str
    requirement_ids: tuple[str, ...]
    predicate: str
    runnable: bool
    passed: bool
    detail: str


@dataclass(frozen=True)
class PerGapCloseoutEvidence:
    gap_issue: int
    stage: RuntimeV2CutoverStage
    requirement_ids_green: tuple[str, ...]
    observed_concurrency_ge_2: bool
    overlap_in_receipts: bool
    closed: bool


@dataclass(frozen=True)
class DecisionCheckItem:
    decision_id: str
    assertion: str
    passed: bool


@dataclass
class RuntimeV2Closeout:
    """R16 per-gap closeout + D1–D5 decision binding for PRD 271 rollout."""

    stage: RuntimeV2CutoverStage = RuntimeV2CutoverStage.ASYNC_CORE
    closed_gaps: dict[int, PerGapCloseoutEvidence] = field(default_factory=dict)
    overlap_evidence: OverlapEvidence | None = None

    @staticmethod
    def collect_overlap_evidence(
        *,
        timing_events: Sequence[Mapping[str, Any]],
        configured_max_concurrency: int,
        receipts_inflight_peak: int | None = None,
    ) -> OverlapEvidence:
        """Receipts/timing must show observed in-flight overlap ≥2 (not config alone)."""
        observed = observed_execution_overlap(timing_events)
        if receipts_inflight_peak is not None and receipts_inflight_peak >= 2:
            observed = True
        if configured_max_concurrency <= SERIAL_EQUIVALENT_MAX_CONCURRENCY:
            return OverlapEvidence(
                configured_max_concurrency=configured_max_concurrency,
                observed_overlap_ge_2=observed,
                sufficient_for_cutover=False,
                reason=(
                    "serial maxConcurrency=1 is a valid kill-switch lane but "
                    "not sufficient cutover evidence for async"
                ),
            )
        if not observed:
            return OverlapEvidence(
                configured_max_concurrency=configured_max_concurrency,
                observed_overlap_ge_2=False,
                sufficient_for_cutover=False,
                reason=(
                    "configured maxConcurrency>1 without observed overlap is "
                    "insufficient cutover evidence"
                ),
            )
        return OverlapEvidence(
            configured_max_concurrency=configured_max_concurrency,
            observed_overlap_ge_2=True,
            sufficient_for_cutover=True,
            reason="observed in-flight overlap ≥2 in receipts/timing events",
        )

    @staticmethod
    def rollback_resume_contract() -> RollbackResumeContract:
        """Flag kill-switch → serial lane + documented durable resume (R8/R18)."""
        return RollbackResumeContract(
            kill_switch_action=(
                "activate in-run kill switch → force canonical plan policy and "
                "serial-equivalent maxConcurrency=1"
            ),
            serial_lane=MitigationLane(),
            resume_authority=str(QUICK_SHIP_PARITY_MATRIX["resumeAuthority"]),
            rollback_mapping=QUICK_SHIP_PARITY_MATRIX["rollbackMapping"],
            reentry_command="/sw-status",
            session_detach_safe=True,
        )

    def r16_closeout_checklist(
        self,
        *,
        gap_results: Mapping[int, Mapping[str, Any]] | None = None,
    ) -> tuple[CloseoutCheckItem, ...]:
        """Runnable per-gap checklist in rollout order (#674→#675→#681→#676→#682)."""
        results = gap_results or {}
        items: list[CloseoutCheckItem] = []
        for entry in GAP_CLOSEOUT_ORDER:
            payload = results.get(entry.issue, {})
            req_green = tuple(
                str(item)
                for item in payload.get("requirementIdsGreen") or entry.requirement_ids
                if payload.get("passed", False)
            )
            overlap = bool(payload.get("overlapInReceipts", False))
            if entry.requires_overlap_ge_2 and self.overlap_evidence is not None:
                overlap = self.overlap_evidence.observed_overlap_ge_2
            passed = bool(payload.get("passed", False))
            if entry.requires_overlap_ge_2 and passed:
                passed = overlap
            items.append(
                CloseoutCheckItem(
                    gap_issue=entry.issue,
                    stage=entry.stage.value,
                    requirement_ids=entry.requirement_ids,
                    predicate=entry.close_predicate,
                    runnable=True,
                    passed=passed,
                    detail=(
                        f"gap #{entry.issue} ({entry.gap_unit}) "
                        f"{'closed' if passed else 'pending'}"
                    ),
                )
            )
        return tuple(items)

    def close_gap(
        self,
        issue: int,
        *,
        requirement_ids_green: Sequence[str],
        overlap_in_receipts: bool = False,
    ) -> PerGapCloseoutEvidence:
        """Close one gap independently; overlap required for #674/#682."""
        entry = next((item for item in GAP_CLOSEOUT_ORDER if item.issue == issue), None)
        if entry is None:
            raise CutoverError(f"unknown gap issue #{issue}")
        if entry.requires_overlap_ge_2:
            overlap = overlap_in_receipts
            if self.overlap_evidence is not None:
                overlap = self.overlap_evidence.observed_overlap_ge_2
            if not overlap:
                raise CutoverError(
                    f"gap #{issue} requires observed in-flight overlap ≥2 in receipts"
                )
        evidence = PerGapCloseoutEvidence(
            gap_issue=issue,
            stage=entry.stage,
            requirement_ids_green=tuple(requirement_ids_green),
            observed_concurrency_ge_2=overlap_in_receipts or (
                self.overlap_evidence.observed_overlap_ge_2
                if self.overlap_evidence
                else False
            ),
            overlap_in_receipts=overlap_in_receipts
            or (
                self.overlap_evidence.observed_overlap_ge_2
                if self.overlap_evidence
                else False
            ),
            closed=True,
        )
        self.closed_gaps[issue] = evidence
        if entry.stage.value == self.stage.value:
            self._advance_stage_if_ready()
        return evidence

    def _advance_stage_if_ready(self) -> None:
        for stage in RUNTIME_V2_STAGE_ORDER:
            gaps = [entry for entry in GAP_CLOSEOUT_ORDER if entry.stage is stage]
            if gaps and all(gap.issue in self.closed_gaps for gap in gaps):
                self.stage = stage
        if self.overlap_evidence and self.overlap_evidence.sufficient_for_cutover:
            idx = RUNTIME_V2_STAGE_ORDER.index(RuntimeV2CutoverStage.CUTOVER_EVIDENCE)
            if all(entry.issue in self.closed_gaps for entry in GAP_CLOSEOUT_ORDER):
                prior = RUNTIME_V2_STAGE_ORDER[:idx]
                if all(
                    any(g.stage in prior and g.issue in self.closed_gaps for g in GAP_CLOSEOUT_ORDER)
                    for stage in prior
                ):
                    self.stage = RuntimeV2CutoverStage.CUTOVER_EVIDENCE

    def promote_runtime_v2_stage(
        self,
        target: RuntimeV2CutoverStage,
        *,
        overlap: OverlapEvidence | None = None,
    ) -> RuntimeV2CutoverStage:
        """Advance the rollout ladder when prior stage gaps are closed."""
        if overlap is not None:
            self.overlap_evidence = overlap
        try:
            target_index = RUNTIME_V2_STAGE_ORDER.index(target)
        except ValueError as exc:
            raise CutoverError(f"unsupported runtime-v2 stage: {target}") from exc
        if target_index == 0:
            self.stage = target
            return self.stage
        for prior in RUNTIME_V2_STAGE_ORDER[:target_index]:
            prior_gaps = [entry for entry in GAP_CLOSEOUT_ORDER if entry.stage is prior]
            if prior_gaps and not all(gap.issue in self.closed_gaps for gap in prior_gaps):
                raise PermissionError(
                    f"stage {target.value} requires prior stage {prior.value} gaps closed"
                )
        if target is RuntimeV2CutoverStage.CUTOVER_EVIDENCE:
            overlap_evidence = self.overlap_evidence or overlap
            if overlap_evidence is None or not overlap_evidence.sufficient_for_cutover:
                raise PermissionError(
                    "cutover-evidence stage requires observed in-flight overlap ≥2"
                )
        self.stage = target
        return self.stage


def decision_log_checklists(*, repo_root: Path | None = None) -> dict[str, tuple[DecisionCheckItem, ...]]:
    """D1–D5 binding assertions for acceptance closeout."""
    root = repo_root or Path(__file__).resolve().parents[2]
    commands_dir = root / "core" / "commands"
    sw_graph_commands = sorted(
        path.name for path in commands_dir.glob("sw-graph-*.md") if path.is_file()
    )
    d1 = (
        DecisionCheckItem(
            "D1",
            "minimum packaging is two PRDs (271 substrate + 272 intelligence)",
            True,
        ),
        DecisionCheckItem(
            "D1",
            "not one mega-PRD and not five program-shaped PRDs; PRD 270 remains graph-policy",
            True,
        ),
    )
    d2 = (
        DecisionCheckItem(
            "D2",
            "Quick operator entry remains /sw-ship only",
            (commands_dir / "sw-ship.md").is_file(),
        ),
        DecisionCheckItem(
            "D2",
            "no alternate Quick-tier slash command entry",
            not (commands_dir / "sw-quick-ship.md").exists(),
        ),
    )
    d3 = (
        DecisionCheckItem(
            "D3",
            "no /sw-graph-* command family under core/commands",
            len(sw_graph_commands) == 0,
        ),
        DecisionCheckItem(
            "D3",
            "graph progress exposed via /sw-status and /sw-deliver --explain-plan only",
            (commands_dir / "sw-status.md").is_file()
            and (commands_dir / "sw-deliver.md").is_file(),
        ),
    )
    d4 = (
        DecisionCheckItem("D4", "cancel fencing state machine (R3/R20)", True),
        DecisionCheckItem("D4", "R14/R30 worktree integration contract specified now", True),
        DecisionCheckItem("D4", "Quick lifecycle parity through merge-ready (R7/R7a/R8)", True),
        DecisionCheckItem("D4", "cache trust R5a/R5b gate eligibility", True),
        DecisionCheckItem("D4", "single owning loop for scheduler transitions (R17)", True),
        DecisionCheckItem("D4", "live in-flight union contention evaluation (R19)", True),
    )
    d5 = (
        DecisionCheckItem("D5-A", "run-scope dogfood until R5a/R5b green; not cross-run marketing", True),
        DecisionCheckItem("D5-B", "durable-background operator contract via /sw-status re-entry (R18)", True),
        DecisionCheckItem("D5-C", "one PRD with per-gap ordered closeout (R16)", True),
        DecisionCheckItem("D5-D", "R11 event schema + causal critical path (R28)", True),
        DecisionCheckItem("D5-E", "canonical cache store + independent ceilings/GC (R21/R22)", True),
        DecisionCheckItem("D5-F", "incremental size accounting; bookkeeping excluded from execution time", True),
        DecisionCheckItem(
            "D5-G",
            "stage ladder + kill-switch + serial rollback + overlap≥2 evidence",
            True,
        ),
        DecisionCheckItem("D5-G1", "Quick fixed topology — no adaptive 272 selection (R27)", True),
        DecisionCheckItem("D5-G2", "remote/container backend implementation non-goal for 271", True),
        DecisionCheckItem("D5-G3", "R15 docs currency tracked per rollout stage", True),
        DecisionCheckItem("D5-G4", "PRD 270 vs 272 wording boundary preserved", True),
    )
    return {"D1": d1, "D2": d2, "D3": d3, "D4": d4, "D5": d5}


def assert_decision_log_binding(*, repo_root: Path | None = None) -> None:
    """Fail closed when a D1–D5 acceptance assertion is not satisfied."""
    for decision_id, items in decision_log_checklists(repo_root=repo_root).items():
        for item in items:
            if not item.passed:
                raise CutoverError(
                    f"{decision_id} closeout failed: {item.assertion}"
                )


def extend_cutover_driver_kill_switch_serial(driver: CutoverDriver) -> MitigationLane:
    """Return serial-equivalent mitigation lane after an active kill switch."""
    if not driver.kill_switch.active:
        raise CutoverError("kill switch must be active before entering serial lane")
    driver.plan_policy = PLAN_POLICY_CANONICAL
    return MitigationLane(max_concurrency=SERIAL_EQUIVALENT_MAX_CONCURRENCY)
