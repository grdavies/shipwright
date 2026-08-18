#!/usr/bin/env python3
"""Atomic legacy deliver-run adoption into run-scoped layout (PRD 081 R18, R21)."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from wave_json_io import StateCorruptError, read_json, write_json
from wave_run_paths import (
    GLOBAL_PLAN_REL,
    RunIdRequiredError,
    global_plan_path,
    mint_run_id,
    plan_path,
    require_run_id,
    state_path,
)
from wave_run_plan import (
    PlanHashMismatchError,
    PlanRecordMissingError,
    compute_plan_hash,
    persist_plan,
    verify_plan_hash,
)
from wave_state import (
    _is_migration_breadcrumb,
    legacy_paths,
    lock_owner_live,
    read_lock_meta,
    reclaim_stale_lock,
    scoped_paths,
    slug_from_target,
    target_branch_from_state,
    utc_now,
)

ADOPT_LOCK_DIR = ".cursor/sw-deliver-adopt-locks"
ADOPT_LOCK_STALE_SECONDS = int(os.environ.get("SW_ADOPT_LOCK_STALE_SECONDS", "300"))


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


def adopt_lock_path(root: Path, run_id: str) -> Path:
    from wave_state import path_normalize_anchor

    rid = require_run_id(run_id)
    safe = rid.replace("/", "_")
    return (path_normalize_anchor(root) / ADOPT_LOCK_DIR / f"{safe}.lock").resolve()


def resume_adopt_command(
    root: Path, run_id: str, task_list: str | None = None
) -> str:
    _ = task_list
    return (
        f"python3 scripts/wave_run_adopt.py {root} adopt --run-id {run_id} --confirm"
    )


def compute_task_list_content_hash(root: Path, task_list_rel: str) -> str | None:
    rel = task_list_rel.strip()
    if not rel:
        return None
    try:
        import planning_materialize as pm
        import planning_path_redirect

        pm.ensure_run_entry_materialized(root, rel)
        _resolved, readable = planning_path_redirect.resolve_readable_path(root, rel)
        candidate = readable if readable is not None and readable.is_file() else root / rel
    except Exception:
        candidate = root / rel
    if not candidate.is_file():
        return None
    from wave_transition_receipt import hash_bytes

    return hash_bytes(candidate.read_bytes())


def assess_proven_run_scoped_identity(
    root: Path,
    state: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Return proven run-scoped identity when plan + task-list content-hash bind."""
    rid_raw = run_id or state.get("runId")
    try:
        rid = require_run_id(str(rid_raw) if rid_raw else None)
    except RunIdRequiredError:
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:run-id-missing",
            "runId": rid_raw,
        }

    scoped_state_path = state_path(root, rid)
    scoped_plan_path = plan_path(root, rid)
    work_state = dict(state)
    if scoped_state_path.is_file():
        on_disk = _read_state_optional(scoped_state_path)
        if on_disk and not _is_migration_breadcrumb(on_disk):
            work_state = {**on_disk, **{k: v for k, v in state.items() if v is not None}}

    if not scoped_plan_path.is_file():
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:run-scoped-plan-missing",
            "runId": rid,
            "planPath": _rel_path(root, scoped_plan_path),
        }

    if not work_state.get("planHash"):
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:plan-hash-missing",
            "runId": rid,
        }

    if not work_state.get("planPath"):
        from wave_run_plan import relative_plan_path

        work_state["planPath"] = relative_plan_path(root, rid)

    try:
        verify_plan_hash(root, rid, work_state)
    except (PlanHashMismatchError, PlanRecordMissingError) as exc:
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": f"adopt:{exc}",
            "runId": rid,
        }

    task_list = work_state.get("source_task_list")
    if not isinstance(task_list, str) or not task_list.strip():
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:source-task-list-missing",
            "runId": rid,
        }

    computed_tl_hash = compute_task_list_content_hash(root, task_list.strip())
    if computed_tl_hash is None:
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:task-list-unreadable",
            "runId": rid,
            "taskList": task_list.strip(),
        }

    recorded_tl_hash = work_state.get("sourceTaskListContentHash")
    if recorded_tl_hash and str(recorded_tl_hash) != computed_tl_hash:
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:task-list-hash-mismatch",
            "runId": rid,
            "recordedTaskListHash": recorded_tl_hash,
            "computedTaskListHash": computed_tl_hash,
        }

    try:
        plan = read_json(scoped_plan_path, absent_ok=False)
    except StateCorruptError as exc:
        return {
            "proven": False,
            "halt": "adopt:identity-unproven",
            "cause": "adopt:run-scoped-plan-corrupt",
            "runId": rid,
            "error": str(exc),
        }

    return {
        "proven": True,
        "runId": rid,
        "plan": plan,
        "planHash": work_state.get("planHash"),
        "sourceTaskListContentHash": computed_tl_hash,
        "taskList": task_list.strip(),
        "state": work_state,
    }


def refuse_unproven_identity(
    root: Path,
    state: dict[str, Any],
    assessment: dict[str, Any],
    *,
    error: str = "run-scoped identity unproven",
    **extra: Any,
) -> None:
    run_id = str(assessment.get("runId") or state.get("runId") or "unknown")
    fail(
        error,
        exit_code=20,
        halt=assessment.get("halt", "adopt:identity-unproven"),
        cause=assessment.get("cause", "adopt:identity-unproven"),
        resumeCommand=resume_adopt_command(
            root, run_id, state.get("source_task_list")
        ),
        **{k: v for k, v in assessment.items() if k not in ("proven", "plan", "state")},
        **extra,
    )


def finalize_identity_refusal(
    root: Path, run_id: str, state: dict[str, Any], assessment: dict[str, Any]
) -> dict[str, Any]:
    return {
        "verdict": "fail",
        "action": "run-finalize",
        "error": assessment.get("cause", "adopt:identity-unproven"),
        "halt": assessment.get("halt", "adopt:identity-unproven"),
        "cause": assessment.get("cause", "adopt:identity-unproven"),
        "resumeCommand": resume_adopt_command(
            root, run_id, state.get("source_task_list")
        ),
        **{k: v for k, v in assessment.items() if k not in ("proven", "plan", "state")},
    }


def _adopt_lock_is_stale(meta: dict[str, Any]) -> bool:
    ts = meta.get("heartbeatAt") or meta.get("acquiredAt")
    if not isinstance(ts, str):
        return True
    try:
        from datetime import datetime, timezone

        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > ADOPT_LOCK_STALE_SECONDS
    except ValueError:
        return True


def _reclaim_stale_adopt_lock(lock_path: Path) -> bool:
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    if lock_owner_live(meta) and not _adopt_lock_is_stale(meta):
        return False
    lock_path.unlink(missing_ok=True)
    return True


def acquire_adopt_lock(root: Path, run_id: str) -> dict[str, Any]:
    lock_path = adopt_lock_path(root, run_id)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    meta: dict[str, Any] = {
        "kind": "adopt-lock",
        "runId": run_id,
        "pid": os.getpid(),
        "threadId": threading.get_ident(),
        "host": socket.gethostname(),
        "acquiredAt": now,
        "heartbeatAt": now,
    }
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    def try_acquire() -> bool:
        try:
            fd = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            return False
        os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
        os.close(fd)
        return True

    if try_acquire():
        return {"verdict": "pass", "lockPath": str(lock_path), "meta": meta}
    existing = read_lock_meta(lock_path)
    if _reclaim_stale_adopt_lock(lock_path) and try_acquire():
        return {
            "verdict": "pass",
            "lockPath": str(lock_path),
            "meta": meta,
            "reclaimed": True,
            "previousHolder": existing,
        }
    if existing.get("runId") == run_id and existing.get("pid") == os.getpid():
        if existing.get("threadId") == threading.get_ident():
            return {"verdict": "pass", "lockPath": str(lock_path), "reentrant": True}
    return {
        "verdict": "fail",
        "error": "adopt-lock-held",
        "halt": "adopt:lock-cas",
        "cause": "adopt:lock-cas",
        "holder": existing,
        "lockPath": str(lock_path),
        "resumeCommand": resume_adopt_command(root, run_id),
    }


def release_adopt_lock(lock_path: Path) -> None:
    if lock_path.is_file():
        lock_path.unlink(missing_ok=True)


@contextmanager
def adopt_lock_guard(root: Path, run_id: str) -> Iterator[dict[str, Any]]:
    acquired = acquire_adopt_lock(root, run_id)
    if acquired.get("verdict") != "pass":
        fail(
            acquired.get("error", "adopt lock acquire failed"),
            exit_code=20,
            **{k: v for k, v in acquired.items() if k != "verdict"},
        )
    lock_path = Path(str(acquired["lockPath"]))
    try:
        yield acquired
    finally:
        release_adopt_lock(lock_path)


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


def _derive_legacy_run_id(
    root: Path, state: dict[str, Any], target: str | None
) -> str:
    existing = state.get("runId")
    if existing:
        try:
            return require_run_id(str(existing))
        except RunIdRequiredError:
            pass
    slug = slug_from_target(target) if target else None
    if slug:
        try:
            return require_run_id(f"deliver-{slug}")
        except RunIdRequiredError:
            pass
    return mint_run_id(root)


def _global_is_full_running_state(root: Path) -> bool:
    legacy = legacy_paths(root)["state"]
    data = _read_state_optional(legacy)
    return bool(
        data
        and not _is_migration_breadcrumb(data)
        and data.get("phases")
        and data.get("verdict") == "running"
    )


def _run_scoped_state_exists(root: Path, run_id: str) -> bool:
    try:
        path = state_path(root, run_id)
    except RunIdRequiredError:
        return False
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
    if len(candidates) > 1:
        if slug or run_id:
            global_layout = [c for c in candidates if c.get("layout") == "global"]
            if len(global_layout) == 1:
                return global_layout[0]
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
    run_id = _derive_legacy_run_id(root, state, target)
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
        scoped_slug = path.name.removeprefix("sw-deliver-state.").removesuffix(".json")
        state = _read_state_optional(path)
        if not state or _is_migration_breadcrumb(state):
            continue
        if not (state.get("phases") or state.get("verdict") == "running"):
            continue
        target = target_branch_from_state(state)
        run_id = _derive_legacy_run_id(root, state, target)
        run_scoped_adopted = _run_scoped_state_exists(root, run_id) and _is_adopted_run_state(
            _read_state_optional(state_path(root, run_id))
        )
        if run_scoped_adopted and not _global_is_full_running_state(root):
            continue
        out.append(
            {
                "layout": "scoped",
                "slug": scoped_slug,
                "runId": run_id,
                "legacyKey": f"legacy-{scoped_slug}",
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
        run_id = _derive_legacy_run_id(root, state, target)
        run_scoped_adopted = _run_scoped_state_exists(root, run_id) and _is_adopted_run_state(
            _read_state_optional(state_path(root, run_id))
        )
        if not (run_scoped_adopted and not _global_is_full_running_state(root)):
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
    identity = assess_proven_run_scoped_identity(root, state, run_id=run_id)
    proven = bool(identity.get("proven"))
    global_plan = legacy_global_plan_path(root)
    plan_exists = global_plan.is_file()
    plan_hash = compute_plan_hash(read_json(global_plan)) if plan_exists else None
    recorded_hash = state.get("planHash")
    hash_mismatch = bool(
        recorded_hash and plan_hash and str(recorded_hash) != str(plan_hash)
    )
    foreign_global_plan = bool(hash_mismatch and proven)
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
        "planHashMismatch": hash_mismatch and not proven,
        "foreignGlobalPlan": foreign_global_plan,
        "provenRunScopedIdentity": proven,
        "preferRunScopedPlan": proven,
        "runScopedPlanHash": identity.get("planHash") if proven else None,
        "sourceTaskListContentHash": identity.get("sourceTaskListContentHash")
        if proven
        else None,
        "runScopedStateExists": _run_scoped_state_exists(root, run_id),
        "runScopedStatePath": _rel_path(root, run_state_path),
        "lock": lock_state_for_target(root, target),
        "adoptLockPath": _rel_path(root, adopt_lock_path(root, run_id)),
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
    with adopt_lock_guard(root, run_id):
        identity = assess_proven_run_scoped_identity(
            root, dict(source["state"]), run_id=run_id
        )
        prefer_run_scoped = bool(identity.get("proven"))
        if preview.get("planHashMismatch") and not prefer_run_scoped:
            fail(
                "plan hash mismatch refuses adoption",
                exit_code=20,
                halt="adopt:plan-hash-mismatch",
                resumeCommand=resume_adopt_command(
                    root, run_id, source.get("taskList")
                ),
                **preview,
            )
        if preview.get("runScopedStateExists") and not abandon and not prefer_run_scoped:
            extra = {
                k: v
                for k, v in preview.items()
                if k not in ("verdict", "action", "recoveryPaths")
            }
            fail(
                "run-scoped state already exists; use inspect or abandon-and-recreate",
                exit_code=20,
                halt="adopt:run-scoped-exists",
                recoveryPaths=preview.get("recoveryPaths"),
                resumeCommand=resume_adopt_command(
                    root, run_id, source.get("taskList")
                ),
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

        if prefer_run_scoped:
            plan = dict(identity["plan"])
            plan_hash = str(identity.get("planHash") or compute_plan_hash(plan))
            task_list_hash = str(identity.get("sourceTaskListContentHash") or "")
            state["sourceTaskListContentHash"] = task_list_hash
            state["planHash"] = plan_hash
            plan_source = "run-scoped"
        else:
            if not legacy_global_plan_path(root).is_file():
                refuse_unproven_identity(
                    root,
                    state,
                    {
                        "proven": False,
                        "halt": "adopt:identity-unproven",
                        "cause": "adopt:run-scoped-plan-missing",
                        "runId": run_id,
                    },
                    error="missing run-scoped plan and global plan",
                )
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
                    resumeCommand=resume_adopt_command(
                        root, run_id, source.get("taskList")
                    ),
                )
            task_list = state.get("source_task_list") or source.get("taskList")
            if isinstance(task_list, str) and task_list.strip():
                tl_hash = compute_task_list_content_hash(root, task_list.strip())
                if tl_hash:
                    state["sourceTaskListContentHash"] = tl_hash
            plan_source = "global"

        state["legacyAdopted"] = True
        state["adoptedAt"] = utc_now()
        state["adoptedPlanHash"] = plan_hash
        state["legacyStatePath"] = source.get("statePath")
        state["legacyPlanPath"] = _rel_path(
            root,
            plan_path(root, run_id)
            if prefer_run_scoped
            else legacy_global_plan_path(root),
        )

        tmp_state = run_state.with_name(run_state.name + ".adopt-tmp")
        write_json(tmp_state, state)
        tmp_state.replace(run_state)

        if not prefer_run_scoped or not plan_path(root, run_id).is_file():
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
            "planSource": plan_source,
        }
        legacy_state = root / str(source["statePath"])
        write_json(legacy_state, breadcrumb)

        return {
            "verdict": "pass",
            "action": "adopt",
            "runId": run_id,
            "adoptedPlanHash": plan_hash,
            "planSource": plan_source,
            "preferRunScopedPlan": prefer_run_scoped,
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
    run_id = state.get("runId") if isinstance(state.get("runId"), str) else None
    identity = (
        assess_proven_run_scoped_identity(root, state, run_id=run_id)
        if run_id
        else {"proven": False}
    )
    if identity.get("proven"):
        if state.get("planHash"):
            return {"adopted": False, "reason": "run-scoped-plan-present"}
    elif state.get("planHash"):
        return {"adopted": False, "reason": "run-scoped-plan-present"}
    target = target_branch_from_state(state)
    slug = target.split("/", 1)[1] if target and "/" in target else None
    source = locate_legacy_source(root, slug=slug, run_id=run_id)
    if not source and legacy_global_plan_path(root).is_file():
        source = locate_legacy_source_from_state(root, state)
    if not source:
        if not identity.get("proven"):
            return {"adopted": False, "reason": "no-legacy-source"}
        refuse_unproven_identity(
            root,
            state,
            identity,
            error="adopt requires proven run-scoped identity or legacy source",
        )
    if source.get("layout") == "scoped" and not identity.get("proven"):
        return {"adopted": False, "reason": "scoped-layout"}
    adopted_run_id = str(source.get("runId") or run_id or "")
    try:
        adopted_run_id = require_run_id(adopted_run_id)
    except RunIdRequiredError:
        adopted_run_id = _derive_legacy_run_id(
            root, dict(source.get("state") or {}), source.get("target")
        )
        source["runId"] = adopted_run_id
    if _run_scoped_state_exists(root, adopted_run_id):
        if _global_is_full_running_state(root):
            result = adopt_legacy_run(root, source, abandon=True)
            return {"adopted": True, **result}
        if _is_adopted_run_state(_read_state_optional(state_path(root, adopted_run_id))):
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
