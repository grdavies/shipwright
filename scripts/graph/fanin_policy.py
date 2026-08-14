#!/usr/bin/env python3
"""Fan-in policy schema + evaluator (PRD 092 R7)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class FanInMode(str, Enum):
    ALL_SUCCESS = "all-success"
    ALL_SETTLED = "all-settled"
    QUORUM = "quorum"
    MINIMUM_COVERAGE = "minimum-coverage"


class CoverageAction(str, Enum):
    HALT = "halt"
    CONTINUE_DEGRADED = "continue-degraded"


@dataclass(frozen=True)
class FanInPolicy:
    mode: FanInMode
    minimum_successful: int | None = None
    required_nodes: frozenset[str] = field(default_factory=frozenset)
    on_insufficient_coverage: CoverageAction = CoverageAction.HALT

    def __post_init__(self) -> None:
        if self.mode in (FanInMode.QUORUM, FanInMode.MINIMUM_COVERAGE):
            if self.minimum_successful is None or self.minimum_successful < 1:
                raise ValueError(f"{self.mode.value} requires minimumSuccessful >= 1")


@dataclass(frozen=True)
class NodeOutcome:
    node_id: str
    success: bool
    settled: bool = True


@dataclass(frozen=True)
class FanInResult:
    verdict: str  # pass | degraded | fail
    halt: bool
    successful: tuple[str, ...]
    failed: tuple[str, ...]
    unsettled: tuple[str, ...]
    missing_required: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "halt": self.halt,
            "successful": list(self.successful),
            "failed": list(self.failed),
            "unsettled": list(self.unsettled),
            "missingRequired": list(self.missing_required),
            "reason": self.reason,
        }


def parse_fanin_policy(raw: dict[str, Any]) -> FanInPolicy:
    mode = FanInMode(str(raw.get("mode") or FanInMode.ALL_SUCCESS.value))
    min_ok = raw.get("minimumSuccessful")
    required = raw.get("requiredNodes") or []
    action_raw = raw.get("onInsufficientCoverage") or CoverageAction.HALT.value
    return FanInPolicy(
        mode=mode,
        minimum_successful=int(min_ok) if min_ok is not None else None,
        required_nodes=frozenset(str(x) for x in required),
        on_insufficient_coverage=CoverageAction(str(action_raw)),
    )


def evaluate_fanin(
    policy: FanInPolicy,
    outcomes: Iterable[NodeOutcome],
    *,
    expected_nodes: Iterable[str] | None = None,
) -> FanInResult:
    """Evaluate fan-in. Failed nodes are never silently dropped from the result."""
    by_id = {o.node_id: o for o in outcomes}
    expected = list(expected_nodes) if expected_nodes is not None else list(by_id.keys())
    successful = tuple(n for n in expected if by_id.get(n) and by_id[n].success and by_id[n].settled)
    failed = tuple(
        n for n in expected if by_id.get(n) and by_id[n].settled and not by_id[n].success
    )
    unsettled = tuple(
        n for n in expected if n not in by_id or not by_id[n].settled
    )
    missing_required = tuple(sorted(n for n in policy.required_nodes if n not in successful))

    def _result(
        verdict: str, halt: bool, reason: str
    ) -> FanInResult:
        return FanInResult(
            verdict=verdict,
            halt=halt,
            successful=successful,
            failed=failed,
            unsettled=unsettled,
            missing_required=missing_required,
            reason=reason,
        )

    if missing_required:
        halt = policy.on_insufficient_coverage == CoverageAction.HALT
        return _result(
            "fail" if halt else "degraded",
            halt,
            f"required nodes not successful: {','.join(missing_required)}",
        )

    if policy.mode == FanInMode.ALL_SUCCESS:
        if unsettled:
            return _result("fail", True, "unsettled predecessors under all-success")
        if failed:
            halt = policy.on_insufficient_coverage == CoverageAction.HALT
            return _result(
                "fail" if halt else "degraded",
                halt,
                f"failed nodes under all-success: {','.join(failed)}",
            )
        return _result("pass", False, "all predecessors successful")

    if policy.mode == FanInMode.ALL_SETTLED:
        if unsettled:
            return _result("fail", True, "unsettled predecessors under all-settled")
        if failed:
            # Settled with failures → degraded visible; halt-by-default
            halt = policy.on_insufficient_coverage == CoverageAction.HALT
            return _result(
                "degraded",
                halt,
                f"settled with failures: {','.join(failed)}",
            )
        return _result("pass", False, "all predecessors settled successfully")

    # quorum / minimum-coverage — settle-before-fire (PRD 269 R2): never admit
    # while any declared predecessor remains unsettled.
    if unsettled:
        return _result(
            "fail",
            True,
            f"unsettled predecessors under {policy.mode.value} settle-before-fire",
        )

    need = int(policy.minimum_successful or 0)
    if len(successful) >= need and not missing_required:
        if failed:
            return _result(
                "degraded",
                False,
                f"quorum met ({len(successful)}>={need}) with visible failures",
            )
        return _result("pass", False, f"quorum met ({len(successful)}>={need})")

    halt = policy.on_insufficient_coverage == CoverageAction.HALT
    return _result(
        "fail" if halt else "degraded",
        halt,
        f"insufficient coverage: successful={len(successful)} need={need}",
    )
