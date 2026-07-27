#!/usr/bin/env python3
"""Atomic legacy deliver-run adoption into run-scoped layout (PRD 081 R18, R21)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from wave_json_io import StateCorruptError, read_json, write_json
from wave_run_paths import GLOBAL_PLAN_REL, global_plan_path, mint_run_id, plan_path, state_path
from wave_run_plan import compute_plan_hash, persist_plan
from wave_state import (
    _is_migration_breadcrumb,
    legacy_paths,
    read_lock_meta,
    scoped_paths,
    slug_from_target,
    target_branch_from_state,
    utc_now,
)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def legacy_global_plan_path(root: Path) -> Path:
    return global_plan_path(root)


def _read_state_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
    except StateCorruptError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_adopted_run_state(state: dict[str, Any]) -> bool:
    return bool(state.get("legacyAdopted") or state.get("adoptedAt"))


def _run_scoped_state_exists(root: Path, run_id: str) -> bool:
    path = state_path(root, run_id)
    if not path.is_file():
        return False
    data = _read_state_optional(path)
    if not data or _is_migration_breadcrumb(data):
        return False
    return bool(data.get("phases") or data.get("verdict") == "running")


def locate_legacy_source(
    root: Path, *, slug: str | None = None, run_id: str | None = None
) -> dict[str, Any] | None:
    """Find legacy/scoped state that still requires adoption."""
    candidates = _legacy_candidates(root)
    if run_id:
        candidates = [
            e
            for e in candidates
            if e.get("runId") == run_id or e.get("legacyKey") == run_id
        ]
    elif slug:
        candidates = [
            e
            for e in candidates
            if e.get("slug") == slug or e.get("legacyKey") == f"legacy-{slug}"
        ]
    if not candidates:
        return None
    if len(candidates) > 1 and not (slug or run_id):
        return None
    return candidates[0]


def locate_legacy_source_from_state(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve an adoption source from the active deliver state payload."""
    if not state.get("phases") or state.get("verdict") != "running":
        return None
    if state.get("legacyAdopted") or state.get("planHash"):
        return None
    target = target_branch_from_state(state)
    slug = target.split("/", 1)[1] if target and "/" in target else None
    run_id = str(state.get("runId") or (f"deliver-{slug}" if slug else "deliver-legacy"))
    from wave_state import resolve_state_path

    state_path = resolve_state_path(root, target=target, state_hint=state)
    try:
        rel = str(state_path.resolve().relative_to(root.resolve()))
    except ValueError:
        rel = str(state_path)
    return {
        "layout": "active",
        "slug": slug or "(legacy)",
        "runId": run_id,
        "legacyKey": f"legacy-{slug}" if slug else "legacy-global",
        "statePath": rel,
        "state": state,
        "target": target,
        "taskList": state.get("source_task_list"),
        "verdict": state.get("verdict"),
    }


def _legacy_candidates(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cursor = root / ".cursor"
    for path in sorted(cursor.glob("sw-deliver-state.*.json")):
        slug = path.name.removeprefix("sw-deliver-state.").removesuffix(".json")
        state = _read_state_optional(path)
        if not state or _is_migration_breadcrumb(state):
            continue
        if not (state.get("phases") or state.get("verdict") == "running"):
            continue
        target = target_branch_from_state(state)
        run_id = str(state.get("runId") or f"deliver-{slug}")
        if _run_scoped_state_exists(root, run_id) and _is_adopted_run_state(
            _read_state_optional(state_path(root, run_id))
        ):
            continue
        out.append(
            {
                "layout": "scoped",
                "slug": slug,
                "runId": run_id,
                "legacyKey": f"legacy-{slug}",
                "statePath": str(path.relative_to(root)),
                "state": state,
                "target": target,
                "taskList": state.get("source_task_list"),
                "verdict": state.get("verdict"),
            }
        )
    legacy = legacy_paths(root)["state"]
    state = _read_state_optional(legacy)
    if state and not _is_migration_breadcrumb(state) and (
        state.get("phases") or state.get("verdict") == "running"
    ):
        target = target_branch_from_state(state)
        slug = slug_from_target(target) if target else "(legacy)"
        run_id = str(state.get("runId") or f"deliver-{slug}")
        if not (
            _run_scoped_state_exists(root, run_id)
            and _is_adopted_run_state(_read_state_optional(state_path(root, run_id)))
        ):
            out.append(
                {
                    "layout": "global",
                    "slug": slug,
                    "runId": run_id,
                    "legacyKey": "legacy-global",
                    "statePath": str(legacy.relative_to(root)),
                    "state": state,
                    "target": target,
                    "taskList": state.get("source_task_list"),
                    "verdict": state.get("verdict"),
                }
            )
    return out


def lock_state_for_target(root: Path, target: str | None) -> dict[str, Any]:
    if not target:
        return {"held": False}
    lock_path = scoped_paths(root, target)["lock"]
    meta = read_lock_meta(lock_path) if lock_path.is_file() else {}
    return {"held": bool(meta), "holder": meta or None, "path": _rel_path(root, lock_path)}


def _rel_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def preview_adoption(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    state = dict(source["state"])
    run_id = str(source["runId"])
    target = source.get("target")
    global_plan = legacy_global_plan_path(root)
    plan_exists = global_plan.is_file()
    plan_hash = compute_plan_hash(read_json(global_plan)) if plan_exists else None
    recorded_hash = state.get("planHash")
    hash_mismatch = bool(
        recorded_hash and plan_hash and str(recorded_hash) != str(plan_hash)
    )
    run_state_path = state_path(root, run_id)
    recovery = []
    if _run_scoped_state_exists(root, run_id):
        recovery.append("inspect")
        recovery.append("abandon-and-recreate")
    else:
        recovery.extend(["adopt", "inspect", "abandon-and-recreate"])
    return {
        "verdict": "pass",
        "action": "adopt-preview",
        "runId": run_id,
        "legacyKey": source.get("legacyKey"),
        "layout": source.get("layout"),
        "statePath": source.get("statePath"),
        "targetBranch": target,
        "taskList": source.get("taskList"),
        "stage": state.get("nextAction"),
        "terminalStatus": state.get("verdict"),
        "globalPlanPath": _rel_path(root, global_plan),
        "globalPlanPresent": plan_exists,
        "recordedPlanHash": recorded_hash,
        "globalPlanHash": plan_hash,
        "planHashMismatch": hash_mismatch,
        "runScopedStateExists": _run_scoped_state_exists(root, run_id),
        "runScopedStatePath": _rel_path(root, run_state_path),
        "lock": lock_state_for_target(root, target),
        "recoveryPaths": recovery,
        "willAdopt": {
            "state": _rel_path(root, run_state_path),
            "plan": _rel_path(root, plan_path(root, run_id)),
            "breadcrumb": source.get("statePath"),
        },
    }


def read_legacy_global_plan_once(root: Path) -> dict[str, Any]:
    """Single permitted read of the repository-global plan (R18/R21)."""
    path = legacy_global_plan_path(root)
    if not path.is_file():
        fail("legacy global plan missing", exit_code=20, halt="adopt:plan-missing", path=str(path))
    try:
        return read_json(path, absent_ok=False)
    except StateCorruptError as exc:
        fail(str(exc), exit_code=20, halt="adopt:plan-corrupt")


def adopt_legacy_run(
    root: Path,
    source: dict[str, Any],
    *,
    abandon: bool = False,
) -> dict[str, Any]:
    preview = preview_adoption(root, source)
    run_id = str(source["runId"])
    run_state = state_path(root, run_id)
    if preview.get("planHashMismatch"):
        fail(
            "plan hash mismatch refuses adoption",
            exit_code=20,
            halt="adopt:plan-hash-mismatch",
            **preview,
        )
    if preview.get("runScopedStateExists") and not abandon:
        extra = {k: v for k, v in preview.items() if k not in ("verdict", "action", "recoveryPaths")}
        fail(
            "run-scoped state already exists; use inspect or abandon-and-recreate",
            exit_code=20,
            halt="adopt:run-scoped-exists",
            recoveryPaths=preview.get("recoveryPaths"),
            **extra,
        )
    if abandon and run_state.is_file():
        run_state.unlink(missing_ok=True)
        plan_path(root, run_id).unlink(missing_ok=True)

    state = dict(source["state"])
    if not state.get("runId"):
        state["runId"] = run_id
    elif str(state["runId"]) != run_id:
        run_id = str(state["runId"])

    plan = read_legacy_global_plan_once(root)
    plan_hash = compute_plan_hash(plan)
    recorded = state.get("planHash")
    if recorded and str(recorded) != plan_hash:
        fail(
            "plan hash mismatch refuses adoption",
            exit_code=20,
            halt="adopt:plan-hash-mismatch",
            recordedPlanHash=recorded,
            globalPlanHash=plan_hash,
        )

    state["legacyAdopted"] = True
    state["adoptedAt"] = utc_now()
    state["adoptedPlanHash"] = plan_hash
    state["legacyStatePath"] = source.get("statePath")
    state["legacyPlanPath"] = _rel_path(root, legacy_global_plan_path(root))

    tmp_state = run_state.with_name(run_state.name + ".adopt-tmp")
    write_json(tmp_state, state)
    tmp_state.replace(run_state)

    persist_plan(root, run_id, plan, state)
    write_json(run_state, state)

    breadcrumb = {
        "migrated": True,
        "adopted": True,
        "adoptedAt": state["adoptedAt"],
        "runId": run_id,
        "runScopedPath": _rel_path(root, run_state),
        "target": source.get("target"),
        "source_task_list": source.get("taskList"),
    }
    legacy_state = root / str(source["statePath"])
    write_json(legacy_state, breadcrumb)

    return {
        "verdict": "pass",
        "action": "adopt",
        "runId": run_id,
        "adoptedPlanHash": plan_hash,
        "statePath": _rel_path(root, run_state),
        "planPath": _rel_path(root, plan_path(root, run_id)),
        "legacyBreadcrumb": _rel_path(root, legacy_state),
    }


def cmd_adopt(root: Path, args: list[str]) -> None:
    slug = parse_kv(args, "--slug")
    run_id = parse_kv(args, "--run-id")
    action = args[0] if args and not args[0].startswith("--") else "preview"
    rest = args[1:] if action in ("preview", "adopt", "inspect", "abandon-and-recreate") else args

    if action not in ("preview", "adopt", "inspect", "abandon-and-recreate"):
        fail(f"unknown adopt action: {action}")

    source = locate_legacy_source(root, slug=slug, run_id=run_id)
    if not source:
        fail(
            "no legacy run found for adoption",
            exit_code=20,
            halt="adopt:not-found",
            slug=slug,
            runId=run_id,
            recoveryPaths=["inspect"],
        )

    preview = preview_adoption(root, source)
    if action == "inspect":
        emit(preview)
    if action == "preview":
        emit(preview)
    if action == "abandon-and-recreate":
        emit(adopt_legacy_run(root, source, abandon=True))
    if action == "adopt":
        if not has_flag(rest, "--confirm") and not has_flag(args, "--confirm"):
            emit({**preview, "verdict": "halt", "halt": "adopt:confirm-required", "remediation": "re-run with --confirm"})
            return
        emit(adopt_legacy_run(root, source, abandon=False))


def maybe_adopt_on_deliver_loop(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Release-bounded single legacy plan read during deliver-loop adoption (R18/R21)."""
    if state.get("legacyAdopted") or state.get("adoptedPlanHash"):
        return {"adopted": False, "reason": "already-adopted"}
    if state.get("planHash"):
        return {"adopted": False, "reason": "run-scoped-plan-present"}
    target = target_branch_from_state(state)
    slug = target.split("/", 1)[1] if target and "/" in target else None
    run_id = state.get("runId") if isinstance(state.get("runId"), str) else None
    source = locate_legacy_source(root, slug=slug, run_id=run_id)
    if not source and legacy_global_plan_path(root).is_file():
        source = locate_legacy_source_from_state(root, state)
    if not source:
        return {"adopted": False, "reason": "no-legacy-source"}
    adopted_run_id = str(source.get("runId") or run_id or "")
    if _run_scoped_state_exists(root, adopted_run_id) and _is_adopted_run_state(
        _read_state_optional(state_path(root, adopted_run_id))
    ):
        return {"adopted": False, "reason": "run-scoped-exists"}
    result = adopt_legacy_run(root, source, abandon=False)
    return {"adopted": True, **result}


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_run_adopt.py <root> <preview|adopt|inspect|abandon-and-recreate> [args...]")
    root = Path(sys.argv[1])
    cmd_adopt(root, sys.argv[2:])


if __name__ == "__main__":
    main()
