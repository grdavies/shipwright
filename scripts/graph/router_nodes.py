#!/usr/bin/env python3
"""First-class router decisions with durable, idempotent events."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass, replace
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Iterable, Mapping

from model_policy_lib import next_model_tier

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# PRD 270 R5 route classes (depth order for regret; cost is tiebreak only).
ROUTE_QUICK = "quick"
ROUTE_LITE = "lite"
ROUTE_FULL_WORKFLOW = "full-workflow"
ROUTE_DETERMINISTIC_TRIAGE = "deterministic-triage"

ROUTE_DEPTH_RANK: dict[str, int] = {
    ROUTE_QUICK: 0,
    ROUTE_LITE: 1,
    ROUTE_FULL_WORKFLOW: 2,
    ROUTE_DETERMINISTIC_TRIAGE: 2,
}

MIN_CALIBRATION_SAMPLE = 3
CALIBRATION_STEP_BOUND = 0.05
HIGH_REGRET_THRESHOLD = 1.0
DEFAULT_QUICK_CONFIDENCE_FLOOR = 0.85

# First-release enumerated deterministic route classes with fixed outcome fields.
DETERMINISTIC_ROUTE_CLASSES: dict[str, dict[str, Any]] = {
    "empty-declared-scope": {
        "selectedRoute": ROUTE_QUICK,
        "readyWithoutRework": True,
        "workflowDepth": ROUTE_QUICK,
        "retries": 0,
        "routingRegret": 0.0,
    },
    "mechanical-gate-halt": {
        "selectedRoute": ROUTE_DETERMINISTIC_TRIAGE,
        "readyWithoutRework": False,
        "workflowDepth": ROUTE_DETERMINISTIC_TRIAGE,
        "retries": 0,
        "routingRegret": 0.0,
    },
    "human-rework-required": {
        "selectedRoute": ROUTE_FULL_WORKFLOW,
        "readyWithoutRework": False,
        "workflowDepth": ROUTE_FULL_WORKFLOW,
        "retries": 0,
        "routingRegret": 1.0,
    },
}


@dataclass(frozen=True)
class RouteRunOutcome:
    """Post-run telemetry used to compute routing regret (R5 ground-truth term)."""

    ready_without_rework: bool
    workflow_depth: str
    retries: int = 0
    cost: float = 0.0
    declared_scope: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    human_rework: bool = False
    mechanical_verification_passed: bool = True

    def __post_init__(self) -> None:
        if self.retries < 0:
            raise ValueError("retries cannot be negative")
        if self.cost < 0:
            raise ValueError("cost cannot be negative")
        if not self.mechanical_verification_passed:
            raise ValueError("mechanical verification cannot be skipped")


@dataclass(frozen=True)
class RouteDecision:
    router_id: str
    input_hash: str
    selected_route: str
    rule_version: str
    classifier_model: str
    confidence: float
    overrides: tuple[str, ...] = ()
    routing_regret: float | None = None

    def __post_init__(self) -> None:
        if not _SAFE_ID.fullmatch(self.router_id):
            raise ValueError("invalid router id")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("route confidence must be between zero and one")
        if self.routing_regret is not None and self.routing_regret < 0:
            raise ValueError("routing regret cannot be negative")

    def with_regret(self, regret: float) -> RouteDecision:
        return replace(self, routing_regret=regret)

    def as_event(self) -> dict[str, Any]:
        value = asdict(self)
        event = {
            "routerId": value["router_id"],
            "inputHash": value["input_hash"],
            "selectedRoute": value["selected_route"],
            "ruleVersion": value["rule_version"],
            "classifierModel": value["classifier_model"],
            "confidence": value["confidence"],
            "overrides": list(value["overrides"]),
        }
        if value["routing_regret"] is not None:
            event["routingRegret"] = value["routing_regret"]
        return event


@dataclass(frozen=True)
class RouteCalibrationSample:
    input_hash: str
    selected_route: str
    routing_regret: float
    ready_without_rework: bool
    cost: float = 0.0


@dataclass(frozen=True)
class CalibrationBucket:
    route_class: str
    samples: tuple[RouteCalibrationSample, ...] = ()
    confidence_floor: float = DEFAULT_QUICK_CONFIDENCE_FLOOR

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def has_minimum_sample(self) -> bool:
        return self.sample_count >= MIN_CALIBRATION_SAMPLE

    def with_sample(self, sample: RouteCalibrationSample) -> CalibrationBucket:
        return CalibrationBucket(
            route_class=self.route_class,
            samples=self.samples + (sample,),
            confidence_floor=self.confidence_floor,
        )

    def apply_bounded_calibration_step(self) -> CalibrationBucket:
        """Adjust confidence floor only when the minimum sample is met."""
        if not self.has_minimum_sample:
            return self
        mean_regret = sum(s.routing_regret for s in self.samples) / len(self.samples)
        raw_step = mean_regret * CALIBRATION_STEP_BOUND
        step = max(-CALIBRATION_STEP_BOUND, min(CALIBRATION_STEP_BOUND, raw_step))
        new_floor = max(0.0, min(1.0, self.confidence_floor + step))
        return CalibrationBucket(
            route_class=self.route_class,
            samples=self.samples,
            confidence_floor=new_floor,
        )


@dataclass(frozen=True)
class RouteCalibrationTable:
    buckets: dict[str, CalibrationBucket]

    @classmethod
    def empty(cls) -> RouteCalibrationTable:
        return cls(buckets={})

    def bucket(self, route_class: str) -> CalibrationBucket:
        return self.buckets.get(route_class, CalibrationBucket(route_class=route_class))

    def with_bucket(self, bucket: CalibrationBucket) -> RouteCalibrationTable:
        return RouteCalibrationTable(
            buckets={**self.buckets, bucket.route_class: bucket}
        )


@dataclass(frozen=True)
class CalibratedRouteSelection:
    selected_route: str
    classifier_tier: str
    response: str
    mechanical_verification_required: bool = True
    routing_regret_tiebreak_cost: float | None = None

    def __post_init__(self) -> None:
        if not self.mechanical_verification_required:
            raise ValueError("mechanical verification cannot be skipped")


def hash_route_input(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_files_changed(
    files: Iterable[str],
    declared_scope: Iterable[str],
) -> tuple[str, ...]:
    """Drop or scope-normalize paths; raw files-changed is not a regret feature."""
    scope = tuple(declared_scope)
    if not scope:
        return ()
    normalized: list[str] = []
    for path in files:
        for pattern in scope:
            if fnmatch(path, pattern) or fnmatch(path, f"**/{pattern}") or path == pattern:
                normalized.append(path)
                break
    return tuple(sorted(set(normalized)))


def compute_routing_regret(
    selected_route: str,
    outcome: RouteRunOutcome,
    *,
    confidence: float | None = None,
) -> float:
    """Regret is calibrated to ready-without-rework; cost is not part of regret."""
    selected_rank = ROUTE_DEPTH_RANK.get(selected_route, 0)
    actual_rank = ROUTE_DEPTH_RANK.get(outcome.workflow_depth, selected_rank)

    regret = 0.0
    if outcome.human_rework or not outcome.ready_without_rework:
        regret += 1.0

    if actual_rank > selected_rank:
        regret += (actual_rank - selected_rank) * 0.5

    if outcome.retries > 0:
        regret += min(1.0, outcome.retries * 0.25)

    if (
        selected_route == ROUTE_QUICK
        and outcome.retries > 0
        and actual_rank >= ROUTE_DEPTH_RANK[ROUTE_FULL_WORKFLOW]
    ):
        regret = max(regret, HIGH_REGRET_THRESHOLD)

    if confidence is not None and selected_route == ROUTE_QUICK and confidence >= 0.9:
        if regret > 0:
            regret = max(regret, HIGH_REGRET_THRESHOLD)

    return regret


def record_routing_regret(
    decision: RouteDecision,
    outcome: RouteRunOutcome,
) -> RouteDecision:
    regret = compute_routing_regret(
        decision.selected_route,
        outcome,
        confidence=decision.confidence,
    )
    return decision.with_regret(regret)


def deterministic_route_for_class(class_name: str) -> dict[str, Any]:
    if class_name not in DETERMINISTIC_ROUTE_CLASSES:
        raise KeyError(class_name)
    return dict(DETERMINISTIC_ROUTE_CLASSES[class_name])


def escalate_classifier_tier(
    current_tier: str,
    triggers: Iterable[str],
    *,
    allowed_tiers: Iterable[str],
    tiers: Mapping[str, str] | None = None,
) -> str:
    """Escalate classifier tier via shared ModelPolicy (never skips mechanical verification)."""
    return next_model_tier(
        current_tier,
        triggers,
        allowed_tiers=allowed_tiers,
        tiers=tiers,
    )


def select_calibrated_route(
    *,
    input_hash: str,
    confidence: float,
    quick_eligible: bool,
    table: RouteCalibrationTable,
    classifier_tier: str,
    allowed_tiers: Iterable[str],
    tiers: Mapping[str, str] | None = None,
    deterministic_class: str | None = None,
    candidate_costs: Mapping[str, float] | None = None,
) -> CalibratedRouteSelection:
    """Choose the next route; below-sample buckets do not influence routing."""
    if deterministic_class is not None:
        fixed = deterministic_route_for_class(deterministic_class)
        return CalibratedRouteSelection(
            selected_route=str(fixed["selectedRoute"]),
            classifier_tier=classifier_tier,
            response="deterministic-equivalence",
            mechanical_verification_required=True,
        )

    route_class = "quick-eligible" if quick_eligible else "standard"
    bucket = table.bucket(route_class).apply_bounded_calibration_step()

    if not bucket.has_minimum_sample:
        return CalibratedRouteSelection(
            selected_route=ROUTE_DETERMINISTIC_TRIAGE,
            classifier_tier=classifier_tier,
            response="deterministic-triage-fallback",
            mechanical_verification_required=True,
        )

    mean_regret = sum(s.routing_regret for s in bucket.samples) / len(bucket.samples)

    if quick_eligible and confidence >= bucket.confidence_floor and mean_regret < 0.5:
        tiebreak_cost = None
        if candidate_costs and ROUTE_QUICK in candidate_costs:
            tiebreak_cost = candidate_costs[ROUTE_QUICK]
        return CalibratedRouteSelection(
            selected_route=ROUTE_QUICK,
            classifier_tier=classifier_tier,
            response="accept",
            mechanical_verification_required=True,
            routing_regret_tiebreak_cost=tiebreak_cost,
        )

    if mean_regret >= HIGH_REGRET_THRESHOLD:
        escalated = escalate_classifier_tier(
            classifier_tier,
            {"low-confidence"},
            allowed_tiers=allowed_tiers,
            tiers=tiers,
        )
        return CalibratedRouteSelection(
            selected_route=ROUTE_FULL_WORKFLOW,
            classifier_tier=escalated,
            response="escalate-classifier-tier",
            mechanical_verification_required=True,
        )

    tiebreak_route = ROUTE_LITE
    tiebreak_cost = None
    if candidate_costs:
        ranked = sorted(
            candidate_costs.items(),
            key=lambda item: (item[1], ROUTE_DEPTH_RANK.get(item[0], 99)),
        )
        tiebreak_route = ranked[0][0]
        tiebreak_cost = ranked[0][1]

    return CalibratedRouteSelection(
        selected_route=tiebreak_route,
        classifier_tier=classifier_tier,
        response="accept",
        mechanical_verification_required=True,
        routing_regret_tiebreak_cost=tiebreak_cost,
    )


class RouteDecisionJournal:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def record(self, event_id: str, decision: RouteDecision) -> dict[str, Any]:
        if not _SAFE_ID.fullmatch(event_id):
            raise ValueError("invalid route event id")
        path = self.root / f"{event_id}.json"
        event = {"eventId": event_id, **decision.as_event()}
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != event:
                raise ValueError("route event id already records another decision")
            return existing
        fd, temporary_name = tempfile.mkstemp(prefix=f".{event_id}.", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(event, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return event

    def record_outcome(
        self,
        event_id: str,
        decision: RouteDecision,
        outcome: RouteRunOutcome,
    ) -> dict[str, Any]:
        """Record routing regret after the run against ready-without-rework."""
        path = self.root / f"{event_id}.json"
        if not path.is_file():
            raise KeyError(event_id)
        existing = json.loads(path.read_text(encoding="utf-8"))
        regret_decision = record_routing_regret(decision, outcome)
        normalized_files = normalize_files_changed(
            outcome.files_changed,
            outcome.declared_scope,
        )
        updated = {
            **existing,
            **regret_decision.as_event(),
            "readyWithoutRework": outcome.ready_without_rework,
            "workflowDepth": outcome.workflow_depth,
            "retries": outcome.retries,
            "costTiebreak": outcome.cost,
            "normalizedFilesChanged": list(normalized_files),
            "mechanicalVerificationRequired": True,
            "mechanicalVerificationPassed": outcome.mechanical_verification_passed,
        }
        if existing.get("routingRegret") is not None and existing != updated:
            if (
                existing.get("routingRegret") == updated.get("routingRegret")
                and existing.get("readyWithoutRework") == updated.get("readyWithoutRework")
            ):
                return existing
            raise ValueError("route outcome already records conflicting regret")
        self._atomic_write(path, updated)
        return updated

    def read(self, event_id: str) -> dict[str, Any]:
        path = self.root / f"{event_id}.json"
        if not path.is_file():
            raise KeyError(event_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise


__all__ = [
    "CALIBRATION_STEP_BOUND",
    "CalibrationBucket",
    "CalibratedRouteSelection",
    "DETERMINISTIC_ROUTE_CLASSES",
    "HIGH_REGRET_THRESHOLD",
    "MIN_CALIBRATION_SAMPLE",
    "ROUTE_DETERMINISTIC_TRIAGE",
    "ROUTE_FULL_WORKFLOW",
    "ROUTE_LITE",
    "ROUTE_QUICK",
    "RouteCalibrationSample",
    "RouteCalibrationTable",
    "RouteDecision",
    "RouteDecisionJournal",
    "RouteRunOutcome",
    "compute_routing_regret",
    "deterministic_route_for_class",
    "escalate_classifier_tier",
    "hash_route_input",
    "normalize_files_changed",
    "record_routing_regret",
    "select_calibrated_route",
]
