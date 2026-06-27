#!/usr/bin/env python3
"""Two-tier plan persistence + single-writer guards (PRD 022 R7, R8, R34, TR4, TR8)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from kernel_classification import load_classification, validate_chain_order
from wave_json_io import StateCorruptError, read_json, write_json
from wave_plan_validate import DEFAULT_PLAN_POLICY, recorded_plan_policy

CALLER_ROLE_ENV = "SW_CALLER_ROLE"
ROLE_CONDUCTOR = "conductor"
ROLE_PHASE = "phase"

PHASE_PLAN_FILENAME = "phase-step-plan.json"
WAVE_PLAN_STATE_KEY = "waveBatchingPlan"
LIFECYCLE_STATE_KEY = "twoTierLifecycle"

LIFECYCLE_WAVE_VALIDATED = "wave-validated"
LIFECYCLE_PHASE_PLAN_PENDING = "phase-plan-pending"
LIFECYCLE_PHASE_PLAN_VALIDATED = "phase-plan-validated"


def caller_role() -> str:
    return os.environ.get(CALLER_ROLE_ENV, ROLE_CONDUCTOR).strip().lower() or ROLE_CONDUCTOR


def require_conductor(exit_fn: Any) -> None:
    if caller_role() != ROLE_CONDUCTOR:
        exit_fn(
            "conductor-only shared run-state write refused",
            exit_code=20,
            callerRole=caller_role(),
            requiredRole=ROLE_CONDUCTOR,
        )


def phase_plan_path(run_dir: Path) -> Path:
    return run_dir / PHASE_PLAN_FILENAME


def resolve_phase_run_dir(phase: str, explicit: str | None = None) -> Path:
    if explicit:
        explicit_path = Path(explicit)
        return explicit_path.parent if explicit_path.suffix == ".json" else explicit_path
    run_dir = os.environ.get("SW_RUN_DIR", "").strip()
    if run_dir:
        return Path(run_dir)
    return Path(".cursor/sw-deliver-runs") / phase


def empty_lifecycle() -> dict[str, Any]:
    return {"wave": None, "phases": {}}


def get_lifecycle(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get(LIFECYCLE_STATE_KEY)
    if not isinstance(raw, dict):
        return empty_lifecycle()
    raw.setdefault("phases", {})
    return raw


def wave_lifecycle(state: dict[str, Any]) -> str | None:
    wave = get_lifecycle(state).get("wave")
    return str(wave) if isinstance(wave, str) else None


def phase_lifecycle(state: dict[str, Any], phase_id: str) -> str | None:
    phases = get_lifecycle(state).get("phases") or {}
    if not isinstance(phases, dict):
        return None
    value = phases.get(phase_id)
    return str(value) if isinstance(value, str) else None


def set_wave_lifecycle(state: dict[str, Any], status: str) -> None:
    lifecycle = get_lifecycle(state)
    lifecycle["wave"] = status
    state[LIFECYCLE_STATE_KEY] = lifecycle


def set_phase_lifecycle(state: dict[str, Any], phase_id: str, status: str) -> None:
    lifecycle = get_lifecycle(state)
    phases = lifecycle.setdefault("phases", {})
    if not isinstance(phases, dict):
        phases = {}
        lifecycle["phases"] = phases
    phases[str(phase_id)] = status
    state[LIFECYCLE_STATE_KEY] = lifecycle


def two_tier_enabled(state: dict[str, Any]) -> bool:
    return LIFECYCLE_STATE_KEY in state


def wave_plan_ready(state: dict[str, Any]) -> bool:
    if not two_tier_enabled(state):
        return True
    return wave_lifecycle(state) == LIFECYCLE_WAVE_VALIDATED


def needs_phase_plan_proposal(state: dict[str, Any], phase_id: str) -> bool:
    if not two_tier_enabled(state):
        return False
    if wave_lifecycle(state) != LIFECYCLE_WAVE_VALIDATED:
        return False
    status = phase_lifecycle(state, phase_id)
    return status in (None, LIFECYCLE_PHASE_PLAN_PENDING)


def validate_phase_plan_document(root: Path, plan: dict[str, Any]) -> tuple[bool, list[str], str]:
    """Return (ok, reasons, disposition) where disposition is pass|halt|replace."""
    reasons: list[str] = []
    if plan.get("tier") != "phase":
        return False, ["plan tier must be phase"], "halt"
    if plan.get("version") != 1:
        return False, ["stale or unsupported plan version"], "replace"
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return False, ["plan steps missing or empty"], "halt"
    policy = recorded_plan_policy(plan) or DEFAULT_PLAN_POLICY
    if policy not in {DEFAULT_PLAN_POLICY, "proposed"}:
        return False, [f"invalid planPolicy: {policy!r}"], "halt"
    classification = load_classification(root)
    current_kernel = str(classification.get("kernelVersion", "1.0.0"))
    stamped = str(plan.get("kernelVersion", ""))
    if stamped and stamped != current_kernel:
        return False, [f"stale kernelVersion {stamped!r} != current {current_kernel!r}"], "replace"
    order_ok, order_reasons = validate_chain_order([str(s) for s in steps], classification)
    if not order_ok:
        reasons.extend(order_reasons)
        return False, reasons, "halt"
    return True, [], "pass"


def load_phase_plan(path: Path, *, absent_ok: bool = True) -> dict[str, Any] | None:
    if not path.is_file():
        if absent_ok:
            return None
        raise StateCorruptError(f"phase plan missing: {path}")
    data = read_json(path)
    if data.get("tier") != "phase":
        raise StateCorruptError(f"invalid phase plan tier: {path}")
    return data


def persist_phase_plan(path: Path, plan: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, plan)


def persist_wave_batching_plan(state: dict[str, Any], plan: dict[str, Any], exit_fn: Any) -> None:
    require_conductor(exit_fn)
    if plan.get("tier") != "wave":
        exit_fn("waveBatchingPlan must have tier wave", exit_code=2)
    state[WAVE_PLAN_STATE_KEY] = plan
    set_wave_lifecycle(state, LIFECYCLE_WAVE_VALIDATED)


def guarded_save_deliver_state(
    root: Path,
    state: dict[str, Any],
    save_fn: Any,
    *,
    target: str | None = None,
    exit_fn: Any | None = None,
) -> Path:
    if exit_fn is None:

        def _default_fail(error: str, exit_code: int = 2, **extra: Any) -> None:
            payload = {"verdict": "fail", "error": error, **extra}
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            sys.exit(exit_code)

        exit_fn = _default_fail
    require_conductor(exit_fn)
    return save_fn(root, state, target=target)


def emit_cli(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail_cli(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit_cli({"verdict": "fail", "error": error, **extra}, exit_code)


def cmd_persist_phase(root: Path, args: list[str]) -> None:
    from ship_phase_steps import _parse_kv

    phase = _parse_kv(args, "--phase") or os.environ.get("SW_PHASE_SLUG", "unknown")
    plan_raw = _parse_kv(args, "--plan")
    if not plan_raw:
        fail_cli("--plan <path|json> required")
    path = Path(plan_raw)
    if path.is_file():
        plan = json.loads(path.read_text(encoding="utf-8"))
    else:
        plan = json.loads(plan_raw)
    if not isinstance(plan, dict):
        fail_cli("plan must be a JSON object")
    out = _parse_kv(args, "--out")
    run_dir = resolve_phase_run_dir(phase, out)
    target = phase_plan_path(run_dir)
    ok, reasons, _ = validate_phase_plan_document(root, plan)
    if not ok:
        fail_cli("refusing to persist invalid phase plan", reasons=reasons, exit_code=20)
    persist_phase_plan(target, plan)
    emit_cli({"verdict": "pass", "action": "persist-phase-plan", "path": str(target), "plan": plan})


def cmd_persist_wave(root: Path, args: list[str]) -> None:
    from ship_phase_steps import _parse_kv
    from wave_state import load_deliver_state, save_deliver_state

    plan_raw = _parse_kv(args, "--plan")
    if not plan_raw:
        fail_cli("--plan <path|json> required")
    path = Path(plan_raw)
    if path.is_file():
        plan = json.loads(path.read_text(encoding="utf-8"))
    else:
        plan = json.loads(plan_raw)
    if not isinstance(plan, dict):
        fail_cli("plan must be a JSON object")
    state = load_deliver_state(root)
    persist_wave_batching_plan(state, plan, fail_cli)
    saved = guarded_save_deliver_state(root, state, save_deliver_state, exit_fn=fail_cli)
    emit_cli(
        {
            "verdict": "pass",
            "action": "persist-wave-plan",
            "path": str(saved),
            "lifecycle": get_lifecycle(state),
        }
    )


def cmd_guarded_state_save(root: Path, args: list[str]) -> None:
    from ship_phase_steps import _parse_kv
    from wave_state import load_deliver_state, save_deliver_state

    state_path = _parse_kv(args, "--state-path")
    if state_path and Path(state_path).is_file():
        state = read_json(Path(state_path))
    else:
        state = load_deliver_state(root)
    patch_raw = _parse_kv(args, "--patch")
    if patch_raw:
        patch = json.loads(patch_raw)
        if isinstance(patch, dict):
            state.update(patch)
    saved = guarded_save_deliver_state(root, state, save_deliver_state, exit_fn=fail_cli)
    emit_cli({"verdict": "pass", "action": "guarded-state-save", "path": str(saved)})


def cmd_lifecycle(root: Path, args: list[str]) -> None:
    from ship_phase_steps import _parse_kv
    from wave_state import load_deliver_state

    sub = args[0] if args else ""
    state = load_deliver_state(root)
    if sub == "get":
        emit_cli({"verdict": "pass", "action": "lifecycle-get", "lifecycle": get_lifecycle(state)})
    if sub == "set-wave":
        status = _parse_kv(args, "--status")
        if not status:
            fail_cli("--status required")
        set_wave_lifecycle(state, status)
        emit_cli({"verdict": "pass", "action": "lifecycle-set-wave", "lifecycle": get_lifecycle(state)})
    if sub == "set-phase":
        phase_id = _parse_kv(args, "--phase-id")
        status = _parse_kv(args, "--status")
        if not phase_id or not status:
            fail_cli("--phase-id and --status required")
        set_phase_lifecycle(state, phase_id, status)
        emit_cli(
            {
                "verdict": "pass",
                "action": "lifecycle-set-phase",
                "phaseId": phase_id,
                "lifecycle": get_lifecycle(state),
            }
        )
    if sub == "needs-phase-proposal":
        phase_id = _parse_kv(args, "--phase-id")
        if not phase_id:
            fail_cli("--phase-id required")
        emit_cli(
            {
                "verdict": "pass",
                "action": "needs-phase-proposal",
                "phaseId": phase_id,
                "needsProposal": needs_phase_plan_proposal(state, phase_id),
                "lifecycle": get_lifecycle(state),
            }
        )
    fail_cli(f"unknown lifecycle subcommand: {sub!r}")


def main() -> None:
    if len(sys.argv) < 3:
        fail_cli(
            "usage: plan_persist.py <root> <persist-phase|persist-wave|guarded-state-save|lifecycle> [args...]"
        )
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    handlers = {
        "persist-phase": cmd_persist_phase,
        "persist-wave": cmd_persist_wave,
        "guarded-state-save": cmd_guarded_state_save,
        "lifecycle": cmd_lifecycle,
    }
    handler = handlers.get(cmd)
    if not handler:
        fail_cli(f"unknown command: {cmd}")
    handler(root, args)


if __name__ == "__main__":
    main()
