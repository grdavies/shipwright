#!/usr/bin/env python3
"""Plan-validation gate — two-tier, closed-world (PRD 022 R6, R32, R33, TR2, TR6)."""
from __future__ import annotations

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from guidelines_validate import load_guidelines
from kernel_classification import (
    canonical_ship_chain,
    chokepoints_reachable_before_merge_push,
    load_classification,
    normalize_step,
    validate_chain_order,
)
from plan_floor_evaluator import floor_mandatory_steps, rule_triggered, validate_plan_against_floor
from orchestrator_guidelines import (
    load_orchestrator_pack,
    pack_signal_conditional_mandatory_steps,
    validate_pack_constraints,
)
from orchestrator_step_plan import (
    VALID_ORCHESTRATOR_TYPES,
    canonical_orchestrator_chain,
    closed_world_vocabulary as orchestrator_closed_world_vocabulary,
    orchestrator_type_spec,
    validate_ordering_invariants as validate_orchestrator_ordering_invariants,
)

REJECTION_THRESHOLD = 3
PLAN_REJECTION_LOG_KEY = "planRejectionLog"
VALID_PLAN_POLICIES = frozenset({"canonical", "proposed"})
DEFAULT_PLAN_POLICY = "canonical"


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (
        ".cursor/workflow.config.json",
        "workflow.config.json",
        ".sw/workflow.config.example.json",
    ):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                continue
    return {}


def read_config_plan_policy(root: Path) -> str:
    """Read orchestration.planPolicy from live workflow config (default canonical)."""
    orch = load_workflow_config(root).get("orchestration") or {}
    policy = str(orch.get("planPolicy", DEFAULT_PLAN_POLICY)).strip().lower()
    return policy if policy in VALID_PLAN_POLICIES else DEFAULT_PLAN_POLICY


def recorded_plan_policy(recorded: dict[str, Any] | None) -> str | None:
    if not isinstance(recorded, dict):
        return None
    policy = str(recorded.get("planPolicy") or "").strip().lower()
    return policy if policy in VALID_PLAN_POLICIES else None


def resolve_plan_policy_for_proposal(
    root: Path,
    *,
    recorded_parent: dict[str, Any] | None = None,
) -> str:
    """Honor recorded planPolicy on resume; otherwise read live config at proposal time."""
    recorded_policy = recorded_plan_policy(recorded_parent)
    if recorded_policy:
        return recorded_policy
    return read_config_plan_policy(root)


def plan_stamps(root: Path, plan_policy: str | None = None, *, recorded_parent: dict[str, Any] | None = None) -> dict[str, str]:
    if plan_policy is None:
        plan_policy = resolve_plan_policy_for_proposal(root, recorded_parent=recorded_parent)
    elif plan_policy not in VALID_PLAN_POLICIES:
        plan_policy = DEFAULT_PLAN_POLICY
    classification = load_classification(root)
    guidelines = load_guidelines(root)
    return {
        "planPolicy": plan_policy,
        "kernelVersion": str(classification.get("kernelVersion", "1.0.0")),
        "guidelineVersion": str(guidelines.get("guidelineVersion", "1.0.0")),
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def load_json_arg(root: Path, raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    path = Path(raw)
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    else:
        data = json.loads(raw)
    return data if isinstance(data, dict) else None


def floor_needs_signal_context(classification: dict[str, Any], task_file_paths: list[str] | None) -> bool:
    matrix = classification.get("floorMatrix") or {}
    for rule in matrix.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        triggers = rule.get("triggers")
        if not isinstance(triggers, dict):
            continue
        if _trigger_references_signal_context(triggers):
            return True
        if task_file_paths:
            continue
        if rule_triggered(rule, None, task_file_paths):
            return True
    return False


def _trigger_references_signal_context(trigger: dict[str, Any]) -> bool:
    if trigger.get("type") == "signal_context":
        return True
    for key in ("anyOf", "allOf", "triggers", "predicates"):
        children = trigger.get(key)
        if isinstance(children, list):
            if any(_trigger_references_signal_context(child) for child in children if isinstance(child, dict)):
                return True
    return False


def check_signal_divergence(embedded: dict[str, Any], persisted: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in (
        "file_paths",
        "derived_tags",
        "tier",
        "doc_path",
        "signal_type",
        "related_files",
        "sentry_ref",
        "source_class",
        "invocation",
        "route",
        "orchestrator_type",
    ):
        if field not in embedded:
            continue
        if embedded.get(field) != persisted.get(field):
            reasons.append(
                f"proposal signal_context.{field} diverges from persisted signal_context"
            )
    return reasons


def closed_world_vocabulary(root: Path, phase_type: str) -> set[str]:
    guidelines = load_guidelines(root)
    guideline = (guidelines.get("phaseTypes") or {}).get(phase_type)
    if not isinstance(guideline, dict):
        return set()
    return {normalize_step(s) for s in guideline.get("candidateSteps") or [] if isinstance(s, str)}


def validate_guideline_constraints(
    guideline: dict[str, Any],
    steps: list[str],
) -> list[str]:
    reasons: list[str] = []
    positions = {step: idx for idx, step in enumerate(steps)}
    for req in guideline.get("requiredSteps") or []:
        norm = normalize_step(str(req))
        if norm not in positions:
            reasons.append(f"required step missing: {norm}")
    for block in guideline.get("forbiddenDeviations") or []:
        if not isinstance(block, dict):
            continue
        omit = block.get("omitStep")
        if isinstance(omit, str) and normalize_step(omit) not in positions:
            reasons.append(f"forbidden omission: {block.get('id', omit)}")
        before = block.get("reorderBefore")
        after = block.get("reorderAfter")
        if isinstance(before, str) and isinstance(after, str):
            b, a = normalize_step(before), normalize_step(after)
            if b in positions and a in positions and positions[b] < positions[a]:
                reasons.append(f"forbidden reorder: {block.get('id', before)}")
    return reasons


def detect_phase_ambiguity(proposal: dict[str, Any], steps: list[str]) -> list[str]:
    reasons: list[str] = []
    if proposal.get("partialOrder"):
        reasons.append("proposal admits multiple valid topological orders (partialOrder)")
    if len(steps) != len(set(steps)):
        reasons.append("duplicate step ids in proposal")
    no_ops = proposal.get("noOpSteps") or []
    if isinstance(no_ops, list) and no_ops:
        reasons.append("duplicate/no-op placeholder steps present")
    return reasons


def validate_kernel_envelope(classification: dict[str, Any], steps: list[str]) -> list[str]:
    reasons: list[str] = []
    order_ok, order_reasons = validate_chain_order(steps, classification)
    if not order_ok:
        reasons.extend(order_reasons)
    for item in classification.get("kernelChokepoints") or []:
        if not isinstance(item, dict):
            continue
        sid = item.get("stepId")
        if sid and item.get("inCanonicalChain") and normalize_step(sid) not in steps:
            reasons.append(f"kernel step missing: {normalize_step(sid)}")
    reach_ok, missing = chokepoints_reachable_before_merge_push(classification, steps)
    if not reach_ok:
        reasons.append(f"chokepoints not reachable before merge/push: {missing}")
    return reasons


def phase_fallback_canonical_chain(
    root: Path,
    phase_type: str = "ship",
    phase_id: str | None = None,
    *,
    recorded_parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamps = plan_stamps(root, recorded_parent=recorded_parent)
    if phase_type == "ship":
        steps = canonical_ship_chain(root)
    else:
        steps = canonical_ship_chain(root)
    return {
        "version": 1,
        "tier": "phase",
        "phaseType": phase_type,
        "phaseId": phase_id,
        "steps": steps,
        "planPolicy": stamps["planPolicy"],
        "kernelVersion": stamps["kernelVersion"],
        "guidelineVersion": stamps["guidelineVersion"],
        "fallback": "canonical-chain",
        "validatedAt": utc_now(),
    }




def validate_orchestrator_constraints(spec: dict[str, Any], steps: list[str]) -> list[str]:
    reasons: list[str] = []
    positions = {step: idx for idx, step in enumerate(steps)}
    for req in spec.get("requiredSteps") or []:
        norm = normalize_step(str(req))
        if norm not in positions:
            reasons.append(f"required step missing: {norm}")
    for forbidden in spec.get("forbiddenSteps") or []:
        norm = normalize_step(str(forbidden))
        if norm in positions:
            reasons.append(f"forbidden step present: {norm}")
    reasons.extend(validate_orchestrator_ordering_invariants(steps, spec.get("orderingInvariants") or []))
    return reasons


def orchestrator_fallback_canonical_chain(
    root: Path,
    orchestrator_type: str,
    orchestrator_id: str | None = None,
    *,
    recorded_parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamps = plan_stamps(root, recorded_parent=recorded_parent)
    steps = canonical_orchestrator_chain(root, orchestrator_type)
    return {
        "version": 1,
        "tier": "orchestrator",
        "orchestratorType": orchestrator_type,
        "orchestratorId": orchestrator_id,
        "steps": steps,
        "planPolicy": stamps["planPolicy"],
        "kernelVersion": stamps["kernelVersion"],
        "guidelineVersion": stamps["guidelineVersion"],
        "fallback": "canonical-chain",
        "validatedAt": utc_now(),
    }



def orchestrator_forbidden_deliver_steps(root: Path, orchestrator_type: str) -> set[str]:
    forbidden: set[str] = set()
    try:
        spec = orchestrator_type_spec(root, orchestrator_type)
        forbidden.update(normalize_step(str(s)) for s in spec.get("forbiddenSteps") or [] if isinstance(s, str))
    except (OSError, ValueError, KeyError):
        pass
    try:
        pack = load_orchestrator_pack(root, orchestrator_type)
        forbidden.update(
            normalize_step(str(s)) for s in pack.get("forbiddenDeliverOnlySteps") or [] if isinstance(s, str)
        )
    except (OSError, ValueError, KeyError):
        pass
    return forbidden


def validate_orchestrator_plan(
    root: Path,
    proposal: dict[str, Any],
    *,
    orchestrator_type: str,
    signal_context: dict[str, Any] | None,
) -> dict[str, Any]:
    steps_raw = proposal.get("steps") or []
    if not isinstance(steps_raw, list) or not steps_raw:
        return {"verdict": "reject", "reasons": ["steps must be a non-empty array"]}

    steps = [normalize_step(str(s)) for s in steps_raw]
    ambiguity = detect_phase_ambiguity(proposal, steps)
    if ambiguity:
        return {"verdict": "ambiguous", "reasons": ambiguity}

    if orchestrator_type not in VALID_ORCHESTRATOR_TYPES:
        return {"verdict": "reject", "reasons": [f"unknown orchestrator type: {orchestrator_type!r}"]}

    vocabulary = orchestrator_closed_world_vocabulary(root, orchestrator_type)
    if not vocabulary:
        return {"verdict": "reject", "reasons": [f"unknown orchestrator type: {orchestrator_type!r}"]}

    forbidden_deliver = orchestrator_forbidden_deliver_steps(root, orchestrator_type)
    deliver_hits = sorted({s for s in steps if s in forbidden_deliver})
    if deliver_hits:
        return {
            "verdict": "reject",
            "reasons": [f"forbidden deliver-only step present: {s}" for s in deliver_hits],
        }

    unknown = sorted({s for s in steps if s not in vocabulary})
    if unknown:
        return {"verdict": "reject", "reasons": [f"unknown/extraneous step id: {s}" for s in unknown]}

    embedded = proposal.get("signal_context") or proposal.get("signals")
    if isinstance(embedded, dict) and signal_context:
        divergence = check_signal_divergence(embedded, signal_context)
        if divergence:
            return {"verdict": "reject", "reasons": divergence}

    spec = orchestrator_type_spec(root, orchestrator_type)
    reasons = validate_orchestrator_constraints(spec, steps)
    try:
        pack = load_orchestrator_pack(root, orchestrator_type)
        reasons.extend(validate_pack_constraints(pack, steps))
        for mandatory in pack_signal_conditional_mandatory_steps(pack, signal_context):
            norm = normalize_step(mandatory)
            if norm not in steps:
                reasons.append(f"signal-conditional floor step missing: {norm}")
    except (OSError, ValueError, KeyError) as exc:
        reasons.append(f"orchestrator guideline pack unavailable: {exc}")
    if reasons:
        if proposal.get("partialOrder"):
            return {"verdict": "ambiguous", "reasons": reasons + ["partial order missing orchestrator ordering pair"]}
        return {"verdict": "reject", "reasons": reasons}

    stamps = plan_stamps(root)
    return {
        "verdict": "pass",
        "reasons": [],
        "plan": {
            "version": 1,
            "tier": "orchestrator",
            "orchestratorType": orchestrator_type,
            "orchestratorId": proposal.get("orchestratorId"),
            "steps": steps,
            **stamps,
            "validatedAt": utc_now(),
        },
    }


def apply_orchestrator_fallback(
    result: dict[str, Any], root: Path, orchestrator_type: str, orchestrator_id: str | None
) -> dict[str, Any]:
    if result.get("verdict") == "pass":
        return result
    fallback = orchestrator_fallback_canonical_chain(root, orchestrator_type, orchestrator_id)
    result["fallback"] = fallback
    result["fallbackAction"] = "canonical-chain"
    return result

def validate_phase_plan(
    root: Path,
    proposal: dict[str, Any],
    *,
    phase_type: str,
    signal_context: dict[str, Any] | None,
    task_file_paths: list[str] | None,
) -> dict[str, Any]:
    steps_raw = proposal.get("steps") or []
    if not isinstance(steps_raw, list) or not steps_raw:
        return {"verdict": "reject", "reasons": ["steps must be a non-empty array"]}

    steps = [normalize_step(str(s)) for s in steps_raw]
    ambiguity = detect_phase_ambiguity(proposal, steps)
    if ambiguity:
        return {"verdict": "ambiguous", "reasons": ambiguity}

    vocabulary = closed_world_vocabulary(root, phase_type)
    if not vocabulary:
        return {"verdict": "reject", "reasons": [f"unknown phase type: {phase_type!r}"]}

    unknown = sorted({s for s in steps if s not in vocabulary})
    if unknown:
        return {"verdict": "reject", "reasons": [f"unknown/extraneous step id: {s}" for s in unknown]}

    embedded = proposal.get("signal_context") or proposal.get("signals")
    if isinstance(embedded, dict) and signal_context:
        divergence = check_signal_divergence(embedded, signal_context)
        if divergence:
            return {"verdict": "reject", "reasons": divergence}

    classification = load_classification(root)
    if floor_needs_signal_context(classification, task_file_paths) and signal_context is None:
        mandatory = floor_mandatory_steps(classification, None, task_file_paths)
        if mandatory:
            return {
                "verdict": "reject",
                "reasons": ["signal_context required for floor evaluation but absent (fail-closed)"],
            }

    floor_ok, floor_reasons = validate_plan_against_floor(
        classification, steps, signal_context, task_file_paths
    )
    if not floor_ok:
        return {"verdict": "reject", "reasons": floor_reasons}

    guidelines = load_guidelines(root)
    guideline = (guidelines.get("phaseTypes") or {}).get(phase_type) or {}
    reasons = validate_guideline_constraints(guideline, steps)
    reasons.extend(validate_kernel_envelope(classification, steps))

    if reasons:
        if proposal.get("partialOrder"):
            return {"verdict": "ambiguous", "reasons": reasons + ["partial order missing kernel ordering pair"]}
        return {"verdict": "reject", "reasons": reasons}

    stamps = plan_stamps(root)
    return {
        "verdict": "pass",
        "reasons": [],
        "plan": {
            "version": 1,
            "tier": "phase",
            "phaseType": phase_type,
            "phaseId": proposal.get("phaseId"),
            "steps": steps,
            **stamps,
            "validatedAt": utc_now(),
        },
    }


def wave_contention_violation(
    proposed_waves: list[list[str]],
    canonical_waves: list[list[str]],
    edges: list[dict[str, str]],
) -> list[str]:
    reasons: list[str] = []
    must_precede: dict[str, set[str]] = {}
    for edge in edges:
        src, dst = edge.get("from"), edge.get("to")
        if isinstance(src, str) and isinstance(dst, str):
            must_precede.setdefault(dst, set()).add(src)

    for wave in proposed_waves:
        if len(wave) < 2:
            continue
        wave_set = set(wave)
        for phase in wave:
            for dep in must_precede.get(phase, set()):
                if dep in wave_set:
                    reasons.append(
                        f"contention/dependency violation: phase {phase} cannot batch with dependency {dep}"
                    )
    canonical_flat = {p for w in canonical_waves for p in w}
    proposed_flat = {p for w in proposed_waves for p in w}
    if proposed_flat != canonical_flat:
        missing = sorted(canonical_flat - proposed_flat)
        extra = sorted(proposed_flat - canonical_flat)
        if missing:
            reasons.append(f"wave proposal missing phases: {missing}")
        if extra:
            reasons.append(f"wave proposal has extraneous phases: {extra}")
    return reasons


def wave_fallback_canonical_waves(
    frozen_plan: dict[str, Any],
    root: Path,
    *,
    recorded_parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stamps = plan_stamps(root, recorded_parent=recorded_parent)
    return {
        "version": 1,
        "tier": "wave",
        "waves": deepcopy(frozen_plan.get("waves") or []),
        "planPolicy": stamps["planPolicy"],
        "kernelVersion": stamps["kernelVersion"],
        "guidelineVersion": stamps["guidelineVersion"],
        "fallback": "canonical-waves",
        "validatedAt": utc_now(),
    }


def wave_fallback_schedule(
    root: Path,
    frozen_plan: dict[str, Any],
    ceiling: int | None = None,
    *,
    recorded_parent: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from wave_deliver import greedy_wave_batches, load_parallel_ceiling

    if ceiling is None:
        ceiling = load_parallel_ceiling(root, [])
    stamps = plan_stamps(root, recorded_parent=recorded_parent)
    waves = frozen_plan.get("waves") or []
    schedule: list[dict[str, Any]] = []
    for wave_index, wave in enumerate(waves, start=1):
        batches = greedy_wave_batches(list(wave), ceiling)
        schedule.append(
            {
                "wave": wave_index,
                "phases": wave,
                "batches": [
                    {
                        "parallel": batch,
                        "slotCount": len(batch),
                        "remainderQueued": index + 1 < len(batches),
                    }
                    for index, batch in enumerate(batches)
                ],
            }
        )
    return {
        "version": 1,
        "tier": "wave",
        "waves": deepcopy(waves),
        "schedule": schedule,
        "parallelCeiling": ceiling,
        "planPolicy": stamps["planPolicy"],
        "kernelVersion": stamps["kernelVersion"],
        "guidelineVersion": stamps["guidelineVersion"],
        "fallback": "schedule",
        "validatedAt": utc_now(),
    }


def derive_canonical_waves_from_task_list(root: Path, task_list: str) -> dict[str, Any]:
    import planning_paths
    from wave_deliver import (
        apply_contention,
        deps_to_edges,
        parse_phase_dependencies,
        parse_phase_files,
        parse_phases,
        resolve_task_list_path,
    )

    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    phases = parse_phases(content)
    dep_rows = parse_phase_dependencies(content)
    phase_files = parse_phase_files(content)
    edges, _ = deps_to_edges(phases, dep_rows, phase_files, root)
    contention = planning_paths.contention_default(root)
    waves, edges, injected, notices, phase_files = apply_contention(
        content, phases, edges, contention, root
    )
    return {
        "waves": waves,
        "edges": edges,
        "injectedEdges": injected,
        "notices": notices,
        "phaseFiles": phase_files,
    }


def validate_wave_plan(
    root: Path,
    proposal: dict[str, Any],
    *,
    frozen_plan: dict[str, Any],
    ceiling: int | None = None,
) -> dict[str, Any]:
    from wave_deliver import load_parallel_ceiling

    proposed_waves = proposal.get("waves")
    if not isinstance(proposed_waves, list) or not proposed_waves:
        return {"verdict": "reject", "reasons": ["waves must be a non-empty array"]}

    if ceiling is None:
        ceiling = load_parallel_ceiling(root, [])

    seen: set[str] = set()
    for wave in proposed_waves:
        if not isinstance(wave, list):
            return {"verdict": "reject", "reasons": ["each wave must be an array of phase ids"]}
        for phase_id in wave:
            if phase_id in seen:
                return {"verdict": "ambiguous", "reasons": [f"duplicate phase id in waves: {phase_id}"]}
            seen.add(str(phase_id))

    canonical_waves = frozen_plan.get("waves") or []
    edges = frozen_plan.get("edges") or []

    over_ceiling = [w for w in proposed_waves if len(w) > ceiling]
    if over_ceiling:
        return {
            "verdict": "reject",
            "reasons": [f"wave exceeds parallelCeiling ({ceiling}): {w}" for w in over_ceiling],
            "fallback": wave_fallback_schedule(root, {**frozen_plan, "waves": proposed_waves}, ceiling),
        }

    contention_reasons = wave_contention_violation(proposed_waves, canonical_waves, edges)
    if contention_reasons:
        return {
            "verdict": "reject",
            "reasons": contention_reasons,
            "fallback": wave_fallback_canonical_waves(frozen_plan, root),
        }

    if proposed_waves != canonical_waves:
        return {
            "verdict": "reject",
            "reasons": ["proposed waves diverge from canonical frozen plan"],
            "fallback": wave_fallback_canonical_waves(frozen_plan, root),
        }

    stamps = plan_stamps(root)
    return {
        "verdict": "pass",
        "reasons": [],
        "plan": {
            "version": 1,
            "tier": "wave",
            "waves": proposed_waves,
            "parallelCeiling": ceiling,
            **stamps,
            "validatedAt": utc_now(),
        },
    }


def apply_undeclared_overlap_serialization(root: Path, task_list: str) -> dict[str, Any]:
    derived = derive_canonical_waves_from_task_list(root, task_list)
    stamps = plan_stamps(root)
    return {
        "version": 1,
        "tier": "wave",
        "waves": derived["waves"],
        "planPolicy": stamps["planPolicy"],
        "kernelVersion": stamps["kernelVersion"],
        "guidelineVersion": stamps["guidelineVersion"],
        "fallback": "contention-serialized",
        "notices": derived.get("notices") or [],
        "injectedEdges": derived.get("injectedEdges") or [],
        "validatedAt": utc_now(),
    }


def empty_rejection_log() -> dict[str, Any]:
    return {"version": 1, "threshold": REJECTION_THRESHOLD, "phases": {}, "halt": None}


def load_rejection_log(state: dict[str, Any]) -> dict[str, Any]:
    log = state.get(PLAN_REJECTION_LOG_KEY)
    if not isinstance(log, dict):
        return empty_rejection_log()
    log.setdefault("version", 1)
    log.setdefault("threshold", REJECTION_THRESHOLD)
    log.setdefault("phases", {})
    log.setdefault("halt", None)
    return log


def append_run_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
    os.chmod(path, 0o600)


def record_plan_rejection(
    state: dict[str, Any],
    *,
    phase_id: str,
    tier: str,
    verdict: str,
    reasons: list[str],
) -> dict[str, Any]:
    log = load_rejection_log(state)
    phases = log.setdefault("phases", {})
    entry = phases.setdefault(
        phase_id,
        {"consecutiveRejections": 0, "entries": []},
    )
    if verdict in {"reject", "ambiguous"}:
        entry["consecutiveRejections"] = int(entry.get("consecutiveRejections", 0)) + 1
        entry.setdefault("entries", []).append(
            {"at": utc_now(), "verdict": verdict, "tier": tier, "reasons": reasons}
        )
    else:
        entry["consecutiveRejections"] = 0

    threshold = int(log.get("threshold", REJECTION_THRESHOLD))
    if entry["consecutiveRejections"] >= threshold:
        log["halt"] = {
            "cause": "plan-rejection-breaker",
            "phaseId": phase_id,
            "consecutiveRejections": entry["consecutiveRejections"],
            "at": utc_now(),
        }
    state[PLAN_REJECTION_LOG_KEY] = log
    return log


def apply_phase_fallback(result: dict[str, Any], root: Path, phase_type: str, phase_id: str | None) -> dict[str, Any]:
    if result.get("verdict") == "pass":
        return result
    fallback = phase_fallback_canonical_chain(root, phase_type, phase_id)
    result["fallback"] = fallback
    result["fallbackAction"] = "canonical-chain"
    return result


def apply_wave_fallback(result: dict[str, Any], root: Path, frozen_plan: dict[str, Any], ceiling: int | None) -> dict[str, Any]:
    if result.get("verdict") == "pass":
        return result
    if result.get("fallback"):
        result["fallbackAction"] = result["fallback"].get("fallback")
        return result
    reasons = result.get("reasons") or []
    if any("parallelCeiling" in r for r in reasons):
        result["fallback"] = wave_fallback_schedule(root, frozen_plan, ceiling)
        result["fallbackAction"] = "schedule"
    else:
        result["fallback"] = wave_fallback_canonical_waves(frozen_plan, root)
        result["fallbackAction"] = "canonical-waves"
    return result


def cmd_validate(root: Path, args: list[str]) -> None:
    tier = parse_kv(args, "--tier")
    if tier not in {"phase", "wave", "orchestrator"}:
        fail("--tier phase|wave|orchestrator required")

    proposal = load_json_arg(root, parse_kv(args, "--proposal"))
    if proposal is None:
        fail("--proposal <path|json> required")

    record = has_flag(args, "--record-rejection")
    phase_id = parse_kv(args, "--phase-id") or proposal.get("phaseId") or "unknown"
    state_path_raw = parse_kv(args, "--state-path")
    run_log_raw = parse_kv(args, "--run-log")

    if tier == "phase":
        phase_type = parse_kv(args, "--phase-type", "ship") or "ship"
        signal_context = load_json_arg(root, parse_kv(args, "--signal-context"))
        task_paths_raw = parse_kv(args, "--task-file-paths", "") or ""
        task_file_paths = [p.strip() for p in task_paths_raw.split(",") if p.strip()] or None

        result = validate_phase_plan(
            root,
            proposal,
            phase_type=phase_type,
            signal_context=signal_context,
            task_file_paths=task_file_paths,
        )
        result = apply_phase_fallback(result, root, phase_type, phase_id)
    elif tier == "orchestrator":
        orchestrator_type = parse_kv(args, "--orchestrator-type")
        if not orchestrator_type or orchestrator_type not in VALID_ORCHESTRATOR_TYPES:
            fail("--orchestrator-type debug|doc|feedback required for orchestrator tier")
        signal_context = load_json_arg(root, parse_kv(args, "--signal-context"))
        orchestrator_id = parse_kv(args, "--orchestrator-id") or proposal.get("orchestratorId") or "unknown"

        result = validate_orchestrator_plan(
            root,
            proposal,
            orchestrator_type=orchestrator_type,
            signal_context=signal_context,
        )
        result = apply_orchestrator_fallback(result, root, orchestrator_type, orchestrator_id)
    else:
        frozen_plan = load_json_arg(root, parse_kv(args, "--frozen-plan"))
        if frozen_plan is None:
            task_list = parse_kv(args, "--task-list")
            if task_list:
                frozen_plan = derive_canonical_waves_from_task_list(root, task_list)
            else:
                fail("--frozen-plan or --task-list required for wave tier")
        ceiling_raw = parse_kv(args, "--ceiling")
        ceiling = int(ceiling_raw) if ceiling_raw else None
        result = validate_wave_plan(root, proposal, frozen_plan=frozen_plan, ceiling=ceiling)
        result = apply_wave_fallback(result, root, frozen_plan, ceiling)

    if record and result.get("verdict") in {"reject", "ambiguous"}:
        state: dict[str, Any] = {}
        if state_path_raw:
            state_path = Path(state_path_raw)
            if state_path.is_file():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    state = {}
        log = record_plan_rejection(
            state,
            phase_id=str(phase_id),
            tier=tier,
            verdict=str(result["verdict"]),
            reasons=list(result.get("reasons") or []),
        )
        result["planRejectionLog"] = log
        if state_path_raw:
            state_path = Path(state_path_raw)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
            os.chmod(state_path, 0o600)
        if log.get("halt"):
            result["halt"] = log["halt"]
            result["breakerTripped"] = True

    log_entry = {
        "event": "plan-validation",
        "tier": tier,
        "phaseId": phase_id,
        "verdict": result.get("verdict"),
        "reasons": result.get("reasons") or [],
    }
    if result.get("breakerTripped"):
        log_entry["breakerTripped"] = True
        log_entry["halt"] = result.get("halt")
    deliver_log = Path(run_log_raw) if run_log_raw else root / ".cursor" / "sw-deliver-runs" / "run.log"
    append_run_log(deliver_log, log_entry)
    if result.get("breakerTripped"):
        append_run_log(
            deliver_log,
            {
                "event": "plan-rejection-breaker",
                "phaseId": phase_id,
                "consecutiveRejections": result.get("halt", {}).get("consecutiveRejections"),
            },
        )

    emit(result, 0 if result.get("verdict") == "pass" else 0)


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_plan_validate.py <root> <command> [args...]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    if cmd == "validate":
        cmd_validate(root, args)
    elif cmd == "serialize-overlaps":
        task_list = parse_kv(args, "--task-list")
        if not task_list:
            fail("--task-list required")
        emit(apply_undeclared_overlap_serialization(root, task_list), 0)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
