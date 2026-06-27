#!/usr/bin/env python3
"""Benefit metric capture, reporting, and R31 decision rule (PRD 023 TR4, R31)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from kernel_classification import canonical_ship_chain

VALID_PLAN_POLICIES = frozenset({"canonical", "proposed"})
VALID_GATE_OUTCOMES = frozenset({"green", "blocked", "red"})
VALID_ESCAPED_DEFECT_SIGNALS = frozenset(
    {"none", "terminal_pr_ci_red", "post_merge_stabilize", "post_merge_revert"}
)
DEFAULT_MIN_N_PER_STRATUM = 3
DEFAULT_WALL_CLOCK_EPSILON = 0.05

VALID_PHASE_STATUSES = frozenset(
    {
        "pending",
        "in-flight",
        "green-merged",
        "teardown-pending",
        "teardown-complete",
        "blocked",
        "rejected",
    }
)

BENEFIT_METRIC_TOP_LEVEL_KEYS = frozenset(
    {
        "planPolicy",
        "kernelVerdict",
        "canonicalStepSet",
        "executedStepSet",
        "stepsSkippedWithoutRework",
        "stabilizeReentries",
        "escapedDefectSignal",
        "phaseWallClockMs",
        "decomposed",
    }
)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def kernel_verdict_key(kernel_verdict: dict[str, Any]) -> str:
    statuses = kernel_verdict.get("terminalPhaseStatuses") or []
    if not isinstance(statuses, list):
        statuses = []
    normalized_statuses = tuple(sorted(str(s) for s in statuses))
    gate = str(kernel_verdict.get("gateOutcome", "blocked")).strip().lower()
    merge_ready = int(kernel_verdict.get("mergeReadyCount", 0))
    return json.dumps(
        {"terminalPhaseStatuses": normalized_statuses, "gateOutcome": gate, "mergeReadyCount": merge_ready},
        sort_keys=True,
    )


def normalize_step_set(steps: list[Any] | None) -> list[str]:
    if not isinstance(steps, list):
        return []
    return [str(s).strip() for s in steps if str(s).strip()]


def normalize_stabilize_reentries(entries: list[Any] | None) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        return []
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        step = str(entry.get("step", "")).strip()
        if not step:
            continue
        normalized.append({"step": step, "attributed": bool(entry.get("attributed"))})
    return normalized


def compute_steps_skipped_without_rework(
    canonical_step_set: list[str],
    executed_step_set: list[str],
    stabilize_reentries: list[dict[str, Any]] | None,
) -> int:
    canonical = set(canonical_step_set)
    executed = set(executed_step_set)
    skipped = canonical - executed
    attributed_steps = {
        entry["step"]
        for entry in normalize_stabilize_reentries(stabilize_reentries)
        if entry.get("attributed")
    }
    return len(skipped - attributed_steps)


def empty_decomposed() -> dict[str, Any]:
    return {
        "stepPlanAdaptivity": {"stepsSkipped": 0, "wallClockMs": 0},
        "waveSchedule": {"wallClockMs": 0},
        "intraPhase": {"wallClockMs": 0},
    }


def build_benefit_metric(
    *,
    plan_policy: str,
    kernel_verdict: dict[str, Any],
    canonical_step_set: list[str] | None = None,
    executed_step_set: list[str] | None,
    stabilize_reentries: list[dict[str, Any]] | None = None,
    escaped_defect_signal: str = "none",
    phase_wall_clock_ms: int = 0,
    decomposed: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    policy = str(plan_policy).strip().lower()
    if policy not in VALID_PLAN_POLICIES:
        fail(f"invalid planPolicy: {plan_policy!r}")
    gate = str(kernel_verdict.get("gateOutcome", "blocked")).strip().lower()
    if gate not in VALID_GATE_OUTCOMES:
        fail(f"invalid kernelVerdict.gateOutcome: {gate!r}")
    escaped = str(escaped_defect_signal).strip().lower()
    if escaped not in VALID_ESCAPED_DEFECT_SIGNALS:
        fail(f"invalid escapedDefectSignal: {escaped_defect_signal!r}")

    canonical = normalize_step_set(
        canonical_step_set if canonical_step_set is not None else canonical_ship_chain(root or Path.cwd())
    )
    executed = normalize_step_set(executed_step_set)
    reentries = normalize_stabilize_reentries(stabilize_reentries)
    steps_skipped = compute_steps_skipped_without_rework(canonical, executed, reentries)

    metric = {
        "planPolicy": policy,
        "kernelVerdict": {
            "terminalPhaseStatuses": sorted(
                str(s) for s in (kernel_verdict.get("terminalPhaseStatuses") or [])
            ),
            "gateOutcome": gate,
            "mergeReadyCount": int(kernel_verdict.get("mergeReadyCount", 0)),
        },
        "canonicalStepSet": canonical,
        "executedStepSet": executed,
        "stepsSkippedWithoutRework": steps_skipped,
        "stabilizeReentries": reentries,
        "escapedDefectSignal": escaped,
        "phaseWallClockMs": max(0, int(phase_wall_clock_ms)),
        "decomposed": decomposed if isinstance(decomposed, dict) else empty_decomposed(),
    }
    violations = sensitive_field_violations(metric)
    if violations:
        fail("benefit metric contains sensitive fields", violations=violations)
    return metric


def _is_allowed_scalar(value: Any) -> bool:
    return isinstance(value, (int, bool)) or value is None


def _is_step_token(value: str) -> bool:
    token = value.strip()
    if not token:
        return False
    for part in token.split("-"):
        if not part or not part.replace("_", "").isalnum():
            return False
    return True


def _walk_sensitive(value: Any, path: str, violations: list[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                violations.append(f"{path}: invalid key")
                continue
            _walk_sensitive(child, f"{path}.{key}" if path else key, violations)
        return
    if isinstance(value, list):
        for idx, child in enumerate(value):
            _walk_sensitive(child, f"{path}[{idx}]", violations)
        return
    if isinstance(value, str):
        allowed_string_paths = {
            "planPolicy",
            "kernelVerdict.gateOutcome",
            "escapedDefectSignal",
        }
        if path in allowed_string_paths:
            if path == "planPolicy" and value not in VALID_PLAN_POLICIES:
                violations.append(f"{path}: disallowed enum {value!r}")
            elif path == "kernelVerdict.gateOutcome" and value not in VALID_GATE_OUTCOMES:
                violations.append(f"{path}: disallowed enum {value!r}")
            elif path == "escapedDefectSignal" and value not in VALID_ESCAPED_DEFECT_SIGNALS:
                violations.append(f"{path}: disallowed enum {value!r}")
        elif path.startswith("canonicalStepSet[") or path.startswith("executedStepSet["):
            if not _is_step_token(value):
                violations.append(f"{path}: disallowed step token {value!r}")
        elif path.startswith("kernelVerdict.terminalPhaseStatuses["):
            if value not in VALID_PHASE_STATUSES:
                violations.append(f"{path}: disallowed phase status {value!r}")
        elif path.endswith(".step"):
            if not _is_step_token(value):
                violations.append(f"{path}: disallowed step token {value!r}")
        else:
            violations.append(f"{path}: free-text string field")
        return
    if not _is_allowed_scalar(value):
        violations.append(f"{path}: disallowed type {type(value).__name__}")


def sensitive_field_violations(metric: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    if not isinstance(metric, dict):
        return ["root: not an object"]
    extra = set(metric.keys()) - BENEFIT_METRIC_TOP_LEVEL_KEYS
    if extra:
        violations.append(f"root: unexpected keys {sorted(extra)}")
    _walk_sensitive(metric, "", violations)
    for step in metric.get("canonicalStepSet") or []:
        if not isinstance(step, str):
            violations.append("canonicalStepSet: non-string step")
    for step in metric.get("executedStepSet") or []:
        if not isinstance(step, str):
            violations.append("executedStepSet: non-string step")
    return violations


def validate_benefit_metric(metric: dict[str, Any]) -> tuple[bool, list[str]]:
    violations = sensitive_field_violations(metric)
    if violations:
        return False, violations
    required = BENEFIT_METRIC_TOP_LEVEL_KEYS - {"decomposed"}
    missing = sorted(required - set(metric.keys()))
    if missing:
        return False, [f"missing keys: {missing}"]
    recomputed = compute_steps_skipped_without_rework(
        normalize_step_set(metric.get("canonicalStepSet")),
        normalize_step_set(metric.get("executedStepSet")),
        metric.get("stabilizeReentries"),
    )
    if int(metric.get("stepsSkippedWithoutRework", -1)) != recomputed:
        return False, [f"stepsSkippedWithoutRework mismatch: recorded={metric.get('stepsSkippedWithoutRework')} recomputed={recomputed}"]
    return True, []


def load_pairs(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("pairs"), list):
        pairs = data["pairs"]
    elif isinstance(data, list):
        pairs = data
    else:
        fail("pairs input must be a list or {\"pairs\": [...]} object")
    normalized: list[dict[str, Any]] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            fail("each pair must be an object")
        canonical = pair.get("canonical")
        proposed = pair.get("proposed")
        if not isinstance(canonical, dict) or not isinstance(proposed, dict):
            fail("each pair requires canonical and proposed benefitMetric objects")
        ok_c, reasons_c = validate_benefit_metric(canonical)
        ok_p, reasons_p = validate_benefit_metric(proposed)
        if not ok_c or not ok_p:
            fail("invalid benefitMetric in pair", canonical=reasons_c, proposed=reasons_p)
        if canonical.get("planPolicy") != "canonical" or proposed.get("planPolicy") != "proposed":
            fail("pair planPolicy must be canonical vs proposed")
        if kernel_verdict_key(canonical["kernelVerdict"]) != kernel_verdict_key(proposed["kernelVerdict"]):
            fail("pair kernelVerdict mismatch")
        normalized.append({"canonical": canonical, "proposed": proposed})
    return normalized


def evaluate_stratum(
    pairs: list[dict[str, Any]],
    *,
    min_n: int,
    epsilon: float,
) -> dict[str, Any]:
    if len(pairs) < min_n:
        return {
            "sufficient": False,
            "positive": False,
            "reason": "insufficient-n",
            "pairCount": len(pairs),
            "minN": min_n,
        }

    for pair in pairs:
        canonical = pair["canonical"]
        proposed = pair["proposed"]
        if int(proposed["stepsSkippedWithoutRework"]) <= int(canonical["stepsSkippedWithoutRework"]):
            return {
                "sufficient": True,
                "positive": False,
                "reason": "steps-skipped-not-positive",
                "pairCount": len(pairs),
                "minN": min_n,
            }
        if proposed.get("escapedDefectSignal", "none") != "none":
            return {
                "sufficient": True,
                "positive": False,
                "reason": "escaped-defect",
                "pairCount": len(pairs),
                "minN": min_n,
            }
        c_wall = int(canonical.get("phaseWallClockMs", 0))
        p_wall = int(proposed.get("phaseWallClockMs", 0))
        limit = int(c_wall * (1.0 + epsilon)) if c_wall > 0 else p_wall
        if c_wall > 0 and p_wall > limit:
            return {
                "sufficient": True,
                "positive": False,
                "reason": "wall-clock-regressed",
                "pairCount": len(pairs),
                "minN": min_n,
                "canonicalWallClockMs": c_wall,
                "proposedWallClockMs": p_wall,
                "epsilon": epsilon,
            }

    return {
        "sufficient": True,
        "positive": True,
        "reason": "positive",
        "pairCount": len(pairs),
        "minN": min_n,
    }


def evaluate_decision_rule(
    pairs: list[dict[str, Any]],
    *,
    min_n: int = DEFAULT_MIN_N_PER_STRATUM,
    epsilon: float = DEFAULT_WALL_CLOCK_EPSILON,
) -> dict[str, Any]:
    strata: dict[str, list[dict[str, Any]]] = {}
    for pair in pairs:
        key = kernel_verdict_key(pair["canonical"]["kernelVerdict"])
        strata.setdefault(key, []).append(pair)

    stratum_results: dict[str, Any] = {}
    overall_positive = True
    overall_sufficient = True
    for key, group in strata.items():
        result = evaluate_stratum(group, min_n=min_n, epsilon=epsilon)
        stratum_results[key] = result
        if not result["sufficient"]:
            overall_sufficient = False
            overall_positive = False
        elif not result["positive"]:
            overall_positive = False

    recommendation = "proposed-eligible" if overall_sufficient and overall_positive else "canonical"
    return {
        "verdict": "pass",
        "recommendation": recommendation,
        "failClosed": recommendation == "canonical",
        "minNPerStratum": min_n,
        "wallClockEpsilon": epsilon,
        "stratumCount": len(strata),
        "pairCount": len(pairs),
        "strata": stratum_results,
    }


def summarize_pairs(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    total_skipped_canonical = sum(int(p["canonical"]["stepsSkippedWithoutRework"]) for p in pairs)
    total_skipped_proposed = sum(int(p["proposed"]["stepsSkippedWithoutRework"]) for p in pairs)
    total_wall_canonical = sum(int(p["canonical"]["phaseWallClockMs"]) for p in pairs)
    total_wall_proposed = sum(int(p["proposed"]["phaseWallClockMs"]) for p in pairs)
    return {
        "pairCount": len(pairs),
        "stepsSkippedWithoutRework": {
            "canonicalTotal": total_skipped_canonical,
            "proposedTotal": total_skipped_proposed,
            "delta": total_skipped_proposed - total_skipped_canonical,
        },
        "phaseWallClockMs": {
            "canonicalTotal": total_wall_canonical,
            "proposedTotal": total_wall_proposed,
            "delta": total_wall_proposed - total_wall_canonical,
        },
    }


def cmd_benefit_report(root: Path, args: list[str]) -> None:
    pairs_path = parse_kv(args, "--pairs")
    if not pairs_path:
        fail("--pairs required (path to paired benefitMetric runs)")
    path = Path(pairs_path)
    if not path.is_file():
        path = root / pairs_path
    if not path.is_file():
        fail(f"pairs file not found: {pairs_path}")

    min_n = int(parse_kv(args, "--min-n", str(DEFAULT_MIN_N_PER_STRATUM)) or DEFAULT_MIN_N_PER_STRATUM)
    epsilon = float(parse_kv(args, "--epsilon", str(DEFAULT_WALL_CLOCK_EPSILON)) or DEFAULT_WALL_CLOCK_EPSILON)
    pairs = load_pairs(path)
    summary = summarize_pairs(pairs)
    decision = evaluate_decision_rule(pairs, min_n=min_n, epsilon=epsilon)
    emit(
        {
            "verdict": "pass",
            "action": "plan-benefit-report",
            "summary": summary,
            "decision": decision,
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_plan_benefit.py <root> benefit-report [args...]")
    root = Path(sys.argv[1])
    command = sys.argv[2]
    args = sys.argv[3:]
    if command == "benefit-report":
        cmd_benefit_report(root, args)
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
