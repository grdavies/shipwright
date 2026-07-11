#!/usr/bin/env python3
"""Run-state, lock, merge journal, and progress log for /sw-deliver phase-mode."""
from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from plan_persist import ROLE_PHASE, caller_role, empty_lifecycle
from pilot_dependency_gate import proposed_pilot_enabled
from wave_json_io import StateCorruptError, read_json, write_json
from quality_config_freeze import pin_from_config, PIN_STATE_KEY
from wave_plan_validate import empty_rejection_log, read_config_plan_policy

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
# Terminal completeness: phase counts as done for retrospective/compound/driver gates (R1/D6).
TERMINAL_PHASE_STATUSES = frozenset({"green-merged", "teardown-pending", "teardown-complete"})
TERMINAL_VERDICTS = frozenset({"running", "complete", "blocked", "rejected"})

_COMPLETION_FINALIZE_DEPTH = 0


@contextlib.contextmanager
def completion_finalize_authorization():
    """Authorize merged-complete writes from finalize-if-merged only (R33)."""
    global _COMPLETION_FINALIZE_DEPTH
    _COMPLETION_FINALIZE_DEPTH += 1
    try:
        yield
    finally:
        _COMPLETION_FINALIZE_DEPTH -= 1


def _assert_completion_finalize_allowed(root: Path, state: dict[str, Any], prior: dict[str, Any] | None) -> None:
    completion = state.get("completion") or {}
    if completion.get("status") != "merged-complete":
        return
    prior_status = ((prior or {}).get("completion") or {}).get("status")
    if prior_status == "merged-complete":
        return
    if os.environ.get("SW_FIXTURE_COMPLETION_FINALIZE") == "1":
        return
    if _COMPLETION_FINALIZE_DEPTH > 0:
        return
    fail(
        "completion.status merged-complete is finalize-only (R33)",
        exit_code=20,
        remediation="python3 scripts/wave.py completion finalize-if-merged",
    )


def phase_complete(status: str | None) -> bool:
    """True when a phase status satisfies terminal completeness (R1)."""
    return status in TERMINAL_PHASE_STATUSES


LOCK_STALE_SECONDS = int(os.environ.get("SW_LOCK_STALE_SECONDS", "3600"))
CANONICAL_STATE_SKEW_SECONDS = 300


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def assert_phase_status(status: str) -> None:
    if status not in VALID_PHASE_STATUSES:
        fail(
            f"invalid phase status {status!r}; allowed: {sorted(VALID_PHASE_STATUSES)}",
            exit_code=20,
            halt="blocked",
            cause="phase-status:invalid",
        )


def fail_corrupt(path: Path, exc: StateCorruptError) -> None:
    fail(
        f"corrupt durable state: {exc}",
        exit_code=20,
        halt="blocked",
        cause="state:corrupt",
        path=str(path),
    )


def load_state_file(path: Path) -> dict[str, Any]:
    try:
        return read_json(path)
    except StateCorruptError as exc:
        fail_corrupt(path, exc)
        return {}  # unreachable


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


LEGACY_STATE_NAME = "sw-deliver-state.json"
LEGACY_LOCK_NAME = "sw-deliver.lock"


def slug_from_target(target_branch: str) -> str:
    if "/" not in target_branch:
        fail(f"invalid target branch: {target_branch!r}")
    return target_branch.split("/", 1)[1]


def target_branch_from_state(state: dict[str, Any]) -> str | None:
    target = state.get("target")
    if isinstance(target, str) and is_feature_target(target):
        return target
    if isinstance(target, dict):
        branch = target.get("branch")
        return branch if isinstance(branch, str) and branch else None
    return None


def scoped_paths(root: Path, target: str) -> dict[str, Path]:
    """Per-branch scoped state/lock paths (PRD 013 R6/R9)."""
    slug = slug_from_target(target)
    cursor = root / ".cursor"
    runs = cursor / "sw-deliver-runs"
    return {
        "state": cursor / f"sw-deliver-state.{slug}.json",
        "lock": cursor / f"sw-deliver-{slug}.lock",
        "log": runs / f"run.{slug}.log",
        "runs": runs,
    }


def legacy_paths(root: Path) -> dict[str, Path]:
    cursor = root / ".cursor"
    runs = cursor / "sw-deliver-runs"
    return {
        "state": cursor / LEGACY_STATE_NAME,
        "lock": cursor / LEGACY_LOCK_NAME,
        "log": runs / "run.legacy.log",
        "runs": runs,
    }


def deliver_run_log_path(root: Path, target: str | None = None, state: dict | None = None) -> Path:
    """Slug-scoped deliver audit log (PRD 050 R4)."""
    return paths(root, target=target, state=state)["log"]

def paths(root: Path, target: str | None = None, state: dict[str, Any] | None = None) -> dict[str, Path]:
    """Resolve durable paths; prefers scoped layout when target is a feature branch."""
    branch = target or (target_branch_from_state(state) if state else None)
    if is_feature_target(branch):
        assert branch is not None
        return scoped_paths(root, branch)
    return legacy_paths(root)


def _task_list_matches_target(root: Path, task_list: str, target: str) -> bool:
    proc = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "wave_deliver.py"),
            str(root),
            "preflight",
            "--task-list",
            task_list,
            "--skip-base-check",
        ],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return False
    branch = (data.get("target") or {}).get("branch")
    return branch == target


def _is_migration_breadcrumb(data: dict[str, Any]) -> bool:
    return data.get("migrated") is True


def _scoped_path_from_breadcrumb(root: Path, data: dict[str, Any]) -> Path | None:
    rel = data.get("scopedPath")
    if isinstance(rel, str):
        path = root / rel
        if path.is_file():
            return path
    target = data.get("target")
    if is_feature_target(target):
        assert target is not None
        scoped = scoped_paths(root, target)["state"]
        return scoped if scoped.is_file() else None
    return None


def _write_legacy_breadcrumb(root: Path, *, target: str, scoped_state: Path) -> None:
    legacy = legacy_paths(root)["state"]
    if legacy == scoped_state:
        return
    breadcrumb = {
        "migrated": True,
        "migratedAt": utc_now(),
        "scopedPath": str(scoped_state.relative_to(root)),
        "target": target,
    }
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(json.dumps(breadcrumb, indent=2) + "\n", encoding="utf-8")
    os.chmod(legacy, 0o600)


def migrate_legacy_state(root: Path, target: str, scoped_state: Path) -> bool:
    """Adopt repo-wide state to scoped path on first read (PRD 013 R11)."""
    legacy = legacy_paths(root)["state"]
    if scoped_state.is_file() or not legacy.is_file():
        return False
    try:
        data = read_json(legacy)
    except StateCorruptError:
        return False
    legacy_target = target_branch_from_state(data)
    task_list = data.get("source_task_list")
    if legacy_target and legacy_target != target:
        return False
    if legacy_target and not is_feature_target(legacy_target):
        return False
    if not legacy_target and isinstance(task_list, str):
        if not _task_list_matches_target(root, task_list, target):
            return False
    elif not legacy_target:
        return False
    scoped_state.parent.mkdir(parents=True, exist_ok=True)
    write_json(scoped_state, data)
    breadcrumb = {
        "migrated": True,
        "migratedAt": utc_now(),
        "scopedPath": str(scoped_state.relative_to(root)),
        "target": target,
        "source_task_list": task_list,
    }
    legacy.write_text(json.dumps(breadcrumb, indent=2) + "\n", encoding="utf-8")
    os.chmod(legacy, 0o600)
    return True


def is_feature_target(target: str | None) -> bool:
    return bool(target and "/" in target)


def _current_feature_branch(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        text=True,
        capture_output=True,
    )
    branch = (proc.stdout or "").strip()
    return branch if is_feature_target(branch) else None


def resolve_state_path(
    root: Path,
    *,
    target: str | None = None,
    task_list: str | None = None,
    state_hint: dict[str, Any] | None = None,
) -> Path:
    """Canonical scoped state file path with legacy migration."""
    if not target and task_list:
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "wave_deliver.py"),
                str(root),
                "preflight",
                "--task-list",
                task_list,
                "--skip-base-check",
            ],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            try:
                data = json.loads(proc.stdout)
                target = (data.get("target") or {}).get("branch")
            except json.JSONDecodeError:
                pass
    if not target and state_hint:
        target = target_branch_from_state(state_hint)
    if is_feature_target(target):
        assert target is not None
        scoped = scoped_paths(root, target)["state"]
        migrate_legacy_state(root, target, scoped)
        return scoped
    legacy = legacy_paths(root)["state"]
    if legacy.is_file():
        try:
            leg_data = read_json(legacy)
        except StateCorruptError:
            leg_data = {}
        if _is_migration_breadcrumb(leg_data):
            scoped = _scoped_path_from_breadcrumb(root, leg_data)
            if scoped is not None:
                return scoped
        else:
            leg_target = target_branch_from_state(leg_data)
            if is_feature_target(leg_target):
                assert leg_target is not None
                scoped = scoped_paths(root, leg_target)["state"]
                if scoped.is_file():
                    return scoped
        return legacy
    matches = sorted((root / ".cursor").glob("sw-deliver-state.*.json"))
    if len(matches) == 1:
        return matches[0]
    return legacy


def enumerate_scoped_runs(root: Path) -> list[dict[str, Any]]:
    """List live scoped deliver runs for index / cleanup (PRD 013 R10)."""
    cursor = root / ".cursor"
    runs: list[dict[str, Any]] = []
    for path in sorted(cursor.glob("sw-deliver-state.*.json")):
        slug = path.name.removeprefix("sw-deliver-state.").removesuffix(".json")
        state = _read_state_optional(path)
        lock_path = cursor / f"sw-deliver-{slug}.lock"
        lock_meta = read_lock_meta(lock_path) if lock_path.is_file() else {}
        runs.append(
            {
                "slug": slug,
                "statePath": str(path.relative_to(root)),
                "taskList": state.get("source_task_list"),
                "verdict": state.get("verdict"),
                "target": (state.get("target") or {}).get("branch"),
                "lockHeld": lock_path.is_file() and bool(lock_meta),
                "lockHolder": lock_meta or None,
            }
        )
    legacy = legacy_paths(root)["state"]
    if legacy.is_file():
        try:
            data = read_json(legacy)
        except StateCorruptError:
            data = {}
        if not _is_migration_breadcrumb(data) and (
            data.get("phases") or data.get("verdict") == "running"
        ):
            runs.append(
                {
                    "slug": "(legacy)",
                    "statePath": str(legacy.relative_to(root)),
                    "taskList": data.get("source_task_list"),
                    "verdict": data.get("verdict"),
                    "target": target_branch_from_state(data),
                    "lockHeld": legacy_paths(root)["lock"].is_file(),
                    "lockHolder": read_lock_meta(legacy_paths(root)["lock"]) or None,
                }
            )
    return runs


def _read_state_optional(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return read_json(path)
    except (StateCorruptError, json.JSONDecodeError):
        return {}



def git_toplevel(start: Path | None = None) -> Path:
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        fail("not a git repository")
    return Path(proc.stdout.strip()).resolve()


def canonical_repo_root(start: Path | None = None) -> Path:
    """Primary repository root for repo-root canonical .cursor state (PRD 049 R4)."""
    start = start or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(start), "rev-parse", "--git-common-dir"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        fail("not a git repository")
    common = Path(proc.stdout.strip())
    if not common.is_absolute():
        common = (Path(start) / common).resolve()
    return common.parent.resolve()


def _parse_state_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _state_updated_skew_seconds(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    left_at = _parse_state_ts(str(left.get("updatedAt") or ""))
    right_at = _parse_state_ts(str(right.get("updatedAt") or ""))
    if not left_at or not right_at:
        return None
    return abs((left_at - right_at).total_seconds())


def _mirror_state_at_root(repo_root: Path, state: dict[str, Any], branch: str) -> None:
    root_path = scoped_paths(repo_root, branch)["state"]
    root_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(root_path, state)


def sync_canonical_state_read(
    start: Path,
    *,
    state_hint: dict[str, Any] | None = None,
    task_list: str | None = None,
    target: str | None = None,
    enforce_skew: bool = True,
) -> dict[str, Any]:
    """Load repo-root canonical deliver state; enforce skew + verdict precedence (PRD 049 R4)."""
    repo_root = canonical_repo_root(start)
    path = resolve_state_path(
        repo_root,
        target=target,
        task_list=task_list,
        state_hint=state_hint,
    )
    root_state = _read_state_optional(path)

    mirror_state: dict[str, Any] = {}
    orch_raw = (root_state.get("orchestratorWorktree") or state_hint or {}).get("path")
    if isinstance(orch_raw, str) and orch_raw.strip():
        orch_root = Path(orch_raw).resolve()
        if orch_root != repo_root.resolve():
            mirror_path = resolve_state_path(
                orch_root,
                target=target or target_branch_from_state(root_state),
                task_list=task_list,
                state_hint=root_state or state_hint,
            )
            mirror_state = _read_state_optional(mirror_path)

    root_has = bool(root_state)
    mirror_has = bool(mirror_state)
    if root_has and mirror_has:
        skew = _state_updated_skew_seconds(root_state, mirror_state)
        if skew is not None and skew > CANONICAL_STATE_SKEW_SECONDS:
            if not enforce_skew:
                return root_state
            fail(
                "canonical deliver state skew exceeds threshold",
                exit_code=20,
                remediation=(
                    "sync state from repo-root canonical copy before terminal deliver steps; "
                    f"skewSeconds={skew}, threshold={CANONICAL_STATE_SKEW_SECONDS}"
                ),
                repoRoot=str(repo_root),
                skewSeconds=skew,
            )
        root_verdict = root_state.get("verdict")
        mirror_verdict = mirror_state.get("verdict")
        if root_verdict != mirror_verdict:
            return root_state

    if root_has:
        return root_state
    return mirror_state


def load_deliver_state(
    root: Path,
    *,
    target: str | None = None,
    task_list: str | None = None,
) -> dict[str, Any]:
    path = resolve_state_path(root, target=target, task_list=task_list)
    try:
        data = read_json(path)
    except StateCorruptError as exc:
        fail_corrupt(path, exc)
        return {}
    if _is_migration_breadcrumb(data):
        scoped = _scoped_path_from_breadcrumb(root, data)
        if scoped is not None:
            try:
                return read_json(scoped)
            except StateCorruptError:
                return {}
        return {}
    return data


def save_deliver_state(
    root: Path,
    state: dict[str, Any],
    *,
    target: str | None = None,
) -> Path:
    if caller_role() == ROLE_PHASE:
        fail(
            "conductor-only shared run-state write refused",
            exit_code=20,
            callerRole=caller_role(),
            requiredRole="conductor",
        )
    branch = target or target_branch_from_state(state)
    if not is_feature_target(branch):
        branch = _current_feature_branch(root)
    if not is_feature_target(branch):
        fail("cannot save deliver state without feature target branch")
    assert branch is not None
    if not target_branch_from_state(state):
        state["target"] = {"branch": branch}
    path = scoped_paths(root, branch)["state"]
    path.parent.mkdir(parents=True, exist_ok=True)
    prior: dict[str, Any] | None = None
    if path.is_file():
        try:
            prior = read_json(path)
        except StateCorruptError:
            prior = None
    _assert_completion_finalize_allowed(root, state, prior)
    state["updatedAt"] = utc_now()
    write_json(path, state)
    _write_legacy_breadcrumb(root, target=branch, scoped_state=path)
    if state.get("orchestratorWorktree"):
        repo_root = canonical_repo_root(root)
        if repo_root.resolve() != root.resolve():
            _mirror_state_at_root(repo_root, state, branch)
    return path


def cmd_resolve_state_path(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    task_list = parse_kv(args, "--task-list")
    path = resolve_state_path(root, target=target, task_list=task_list)
    emit(
        {
            "verdict": "pass",
            "action": "resolve-state-path",
            "path": str(path),
            "relative": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
        }
    )


def cmd_resolve_lock_path(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if not target:
        fail("--target required")
    path = scoped_paths(root, target)["lock"]
    emit(
        {
            "verdict": "pass",
            "action": "resolve-lock-path",
            "path": str(path),
            "relative": str(path.relative_to(root)),
        }
    )


def cmd_runs_index(root: Path, _args: list[str]) -> None:
    runs = enumerate_scoped_runs(root)
    index_path = root / ".cursor" / "sw-deliver-runs" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"updatedAt": utc_now(), "runs": runs}
    index_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.chmod(index_path, 0o600)
    emit({"verdict": "pass", "action": "runs-index", "runs": runs, "path": str(index_path)})


def lock_host() -> str:
    return socket.gethostname()


def lock_is_stale(meta: dict[str, Any]) -> bool:
    ts = meta.get("heartbeatAt") or meta.get("acquiredAt")
    if not isinstance(ts, str):
        return True
    try:
        dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        return age > LOCK_STALE_SECONDS
    except ValueError:
        return True


def lock_owner_live(meta: dict[str, Any]) -> bool:
    """Lock is live when heartbeat is fresh or the recorded pid is still running."""
    if not lock_is_stale(meta):
        return True
    pid = meta.get("pid")
    if isinstance(pid, int) and pid > 0:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    return False


def read_lock_meta(lock_path: Path) -> dict[str, Any]:
    if not lock_path.is_file():
        return {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def reclaim_stale_lock(lock_path: Path) -> bool:
    """Remove lock when owner is dead or heartbeat is stale. Returns True if reclaimed."""
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    if lock_owner_live(meta):
        return False
    lock_path.unlink(missing_ok=True)
    return True


def append_log(root: Path, entry: dict[str, Any], *, target: str | None = None) -> None:
    p = paths(root, target=target)
    p["runs"].mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with open(p["log"], "a", encoding="utf-8") as f:
        f.write(line)
    os.chmod(p["log"], 0o600)


def cmd_state_init(root: Path, args: list[str]) -> None:
    plan_path = parse_kv(args, "--plan")
    if not plan_path:
        fail("--plan required")
    plan_file = (root / plan_path).resolve()
    if not plan_file.is_file():
        fail(f"plan not found: {plan_path}")
    plan = json.loads(plan_file.read_text(encoding="utf-8"))
    if plan.get("mode") != "phase":
        fail("state init requires phase-mode plan")

    phases: dict[str, Any] = {}
    for item in plan.get("items") or []:
        pid = str(item.get("id", ""))
        if not pid:
            continue
        phases[pid] = {
            "id": pid,
            "slug": item.get("slug", ""),
            "title": item.get("title", ""),
            "branch": item.get("branch", ""),
            "status": "pending",
            "updatedAt": utc_now(),
        }

    state = {
        "verdict": "running",
        "target": plan.get("target"),
        "source_task_list": plan.get("source_task_list"),
        "prd_number": plan.get("prd_number"),
        "phases": phases,
        "mergeJournal": None,
        "completedMerges": [],
        "currentWave": 1,
        "nextAction": "lock-acquire",
        "remediationAttempts": {},
        "phaseWorktrees": {},
        "driverHeartbeatAt": utc_now(),
        "updatedAt": utc_now(),
    }
    cfg: dict = {}
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        p = root / rel
        if p.is_file():
            try:
                cfg = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cfg = {}
            break
    state[PIN_STATE_KEY] = pin_from_config(cfg)
    if read_config_plan_policy(root) == "proposed":
        if not proposed_pilot_enabled(root):
            fail(
                "proposed planPolicy refused: 022 dependency gate not satisfied",
                exit_code=20,
                halt="blocked",
                cause="pilot-dependency-gate",
                requiredFixtures=sorted(
                    {
                        "exec-fidelity-out-of-order-halt",
                        "resume-two-tier-deterministic",
                        "resume-corrupt-plan-fail-closed",
                    }
                ),
            )
        state["twoTierLifecycle"] = empty_lifecycle()
        state["planRejectionLog"] = empty_rejection_log()
    write_json(resolve_state_path(root, task_list=plan.get("source_task_list"), target=(plan.get("target") or {}).get("branch")), state)
    append_log(
        root,
        {
            "event": "run-init",
            "target": (plan.get("target") or {}).get("branch"),
            "phaseCount": len(phases),
        },
    )
    emit({"verdict": "pass", "action": "state-init", "phaseCount": len(phases)})


def find_phase(state: dict[str, Any], phase_id: str | None, slug: str | None) -> tuple[str, dict[str, Any]]:
    phases = state.get("phases") or {}
    if phase_id:
        if phase_id not in phases:
            fail(f"unknown phase id {phase_id!r}")
        return phase_id, phases[phase_id]
    if slug:
        for pid, meta in phases.items():
            if meta.get("slug") == slug:
                return pid, meta
        fail(f"unknown phase slug {slug!r}")
    fail("--id or --slug required")


def _ops_state_path(root: Path, args: list[str]) -> Path:
    target = parse_kv(args, "--target")
    task_list = parse_kv(args, "--task-list")
    return resolve_state_path(root, target=target, task_list=task_list)


def cmd_state_phase(root: Path, args: list[str]) -> None:
    status = parse_kv(args, "--status")
    if not status:
        fail(f"--status required; one of {sorted(VALID_PHASE_STATUSES)}")
    assert_phase_status(status)
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path)
    if not state:
        fail("run state missing; run state init first", exit_code=2)

    pid, meta = find_phase(state, parse_kv(args, "--id"), parse_kv(args, "--slug"))
    old_status = meta.get("status")
    state["phases"][pid]["status"] = status
    state["phases"][pid]["updatedAt"] = utc_now()
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(
        root,
        {
            "event": "phase-transition",
            "phaseId": pid,
            "phaseSlug": meta.get("slug"),
            "from": old_status,
            "to": status,
        },
    )
    emit({"verdict": "pass", "action": "state-phase", "phaseId": pid, "status": status})


def cmd_state_heartbeat(root: Path, args: list[str]) -> None:
    """Refresh driverHeartbeatAt for liveness / watchdog (R37)."""
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path)
    if not state:
        fail("run state missing; run state init first", exit_code=2)
    now = utc_now()
    state["driverHeartbeatAt"] = now
    state["updatedAt"] = now
    write_json(state_path, state)
    emit({"verdict": "pass", "action": "state-heartbeat", "driverHeartbeatAt": now})


def cmd_state_get(root: Path, args: list[str]) -> None:
    state_path = _ops_state_path(root, args)
    if not state_path.is_file():
        emit({"verdict": "pass", "state": None, "present": False})
    state = load_state_file(state_path)
    emit({"verdict": "pass", "present": True, "state": state})


def cmd_state_terminal(root: Path, args: list[str]) -> None:
    verdict = parse_kv(args, "--verdict")
    if not verdict or verdict not in TERMINAL_VERDICTS:
        fail(f"--verdict required; one of {sorted(TERMINAL_VERDICTS)}")
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path)
    if not state:
        fail("run state missing")
    state["verdict"] = verdict
    state["updatedAt"] = utc_now()
    cause = parse_kv(args, "--cause")
    if cause:
        state["cause"] = cause
    write_json(state_path, state)
    append_log(root, {"event": "run-terminal", "verdict": verdict, "cause": cause})
    emit({"verdict": "pass", "action": "state-terminal", "runVerdict": verdict})


def cmd_lock_acquire(root: Path, args: list[str]) -> None:
    """Atomic orchestrator lock (R41): O_CREAT|O_EXCL — concurrent acquire yields exit 20."""
    target = parse_kv(args, "--target")
    if not target:
        fail("--target required (e.g. feat/my-slug)")
    nonblock = "--nonblock" in args
    lock_path = scoped_paths(root, target)["lock"]
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    meta = {
        "target": target,
        "pid": os.getpid(),
        "host": lock_host(),
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

    if not try_acquire():
        existing = read_lock_meta(lock_path)
        if reclaim_stale_lock(lock_path) and try_acquire():
            append_log(
                root,
                {
                    "event": "lock-reclaim",
                    "target": target,
                    "previousHolder": existing,
                },
            )
        else:
            fail("orchestrator lock held", exit_code=20, holder=existing)
    append_log(root, {"event": "lock-acquire", "target": target})
    emit({"verdict": "pass", "action": "lock-acquire", "target": target})


def _resolve_lock_path(root: Path, args: list[str]) -> Path:
    target = parse_kv(args, "--target")
    if target:
        return scoped_paths(root, target)["lock"]
    lock_path = legacy_paths(root)["lock"]
    if lock_path.is_file():
        return lock_path
    matches = [
        p
        for p in sorted((root / ".cursor").glob("sw-deliver-*.lock"))
        if p.name != LEGACY_LOCK_NAME
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return lock_path
    fail("--target required when multiple scoped locks exist")


def cmd_lock_release(root: Path, args: list[str]) -> None:
    lock_path = _resolve_lock_path(root, args)
    if not lock_path.is_file():
        emit({"verdict": "pass", "action": "lock-release", "note": "no lock file"})
    meta: dict[str, Any] = {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw:
            meta = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        pass
    lock_path.unlink(missing_ok=True)
    append_log(root, {"event": "lock-release", "target": meta.get("target")})
    emit({"verdict": "pass", "action": "lock-release"})


def cmd_lock_status(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if target:
        lock_path = scoped_paths(root, target)["lock"]
    else:
        lock_path = _resolve_lock_path(root, args)
    if not lock_path.is_file():
        emit({"verdict": "pass", "held": False})
    meta: dict[str, Any] = {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
        if raw:
            meta = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        meta = {}
    emit({"verdict": "pass", "held": True, "lock": meta})


def cmd_journal_begin(root: Path, args: list[str]) -> None:
    slug = parse_kv(args, "--phase")
    if not slug:
        fail("--phase required")
    head = parse_kv(args, "--head", "")
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path)
    if not state:
        fail("run state missing")
    completed = state.get("completedMerges") or []
    merge_key = f"{slug}:{head}" if head else slug
    if any(c.get("key") == merge_key for c in completed if isinstance(c, dict)):
        emit(
            {
                "verdict": "pass",
                "action": "journal-begin",
                "note": "already completed (idempotent)",
                "journal": None,
            }
        )
    open_journal = state.get("mergeJournal")
    if open_journal:
        if open_journal.get("phase") == slug and (
            not head or open_journal.get("head") == head or not open_journal.get("head")
        ):
            emit(
                {
                    "verdict": "pass",
                    "action": "journal-begin",
                    "note": "journal already open (resume)",
                    "journal": open_journal,
                }
            )
        fail(
            "merge journal already open",
            exit_code=20,
            journal=open_journal,
        )
    journal = {
        "phase": slug,
        "head": head or None,
        "startedAt": utc_now(),
        "key": merge_key,
    }
    state["mergeJournal"] = journal
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "merge-begin", "phase": slug, "head": head})
    emit({"verdict": "pass", "action": "journal-begin", "journal": journal})


def cmd_journal_complete(root: Path, args: list[str]) -> None:
    slug = parse_kv(args, "--phase")
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path)
    journal = state.get("mergeJournal")
    if not journal:
        completed = state.get("completedMerges") or []
        if slug and any(
            isinstance(c, dict) and c.get("phase") == slug for c in completed
        ):
            emit(
                {
                    "verdict": "pass",
                    "action": "journal-complete",
                    "note": "already completed (idempotent)",
                }
            )
        fail("no open merge journal")
    if slug and journal.get("phase") != slug:
        fail(f"journal phase mismatch: open={journal.get('phase')!r} requested={slug!r}")
    completed = {**journal, "completedAt": utc_now()}
    done = list(state.get("completedMerges") or [])
    key = journal.get("key") or journal.get("phase")
    if not any(isinstance(c, dict) and c.get("key") == key for c in done):
        done.append(
            {
                "key": key,
                "phase": journal.get("phase"),
                "head": journal.get("head"),
                "completedAt": completed["completedAt"],
            }
        )
    state["mergeJournal"] = None
    state["completedMerges"] = done
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "merge-complete", "phase": journal.get("phase")})
    emit({"verdict": "pass", "action": "journal-complete", "journal": completed})


def cmd_journal_status(root: Path, args: list[str]) -> None:
    state = load_state_file(_ops_state_path(root, args))
    journal = state.get("mergeJournal")
    emit({"verdict": "pass", "open": journal is not None, "journal": journal})


def cmd_log_tail(root: Path, args: list[str]) -> None:
    lines = int(parse_kv(args, "--lines", "10") or "10")
    target = parse_kv(args, "--target")
    log_path = paths(root, target=target)["log"]
    if not log_path.is_file():
        emit({"verdict": "pass", "entries": []})
    content = log_path.read_text(encoding="utf-8").strip().splitlines()
    entries = []
    for line in content[-lines:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    emit({"verdict": "pass", "entries": entries})


def _task_ledger(state: dict[str, Any]) -> dict[str, Any]:
    ledger = state.get("taskLedger")
    if not isinstance(ledger, dict):
        ledger = {"tasks": {}, "phases": {}}
    ledger.setdefault("tasks", {})
    ledger.setdefault("phases", {})
    return ledger


def load_task_ledger(
    root: Path,
    *,
    target: str | None = None,
    task_list: str | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Reusable accessor for ``state.taskLedger`` on deliver run-state (PRD 059 R9)."""
    if state is None:
        state = load_deliver_state(root, target=target, task_list=task_list)
    return dict(_task_ledger(state))


def task_ledger_tasks(state: dict[str, Any]) -> dict[str, Any]:
    """Return the ``tasks`` map from durable deliver run-state ledger."""
    tasks = load_task_ledger(root=Path("."), state=state).get("tasks") or {}
    return tasks if isinstance(tasks, dict) else {}


def _hierarchy_map(state: dict[str, Any]) -> dict[str, Any]:
    hmap = state.get("hierarchyMap")
    if not isinstance(hmap, dict):
        hmap = {}
    return hmap


def load_hierarchy_map(state: dict[str, Any]) -> dict[str, Any]:
    """Return durable hierarchyMap from deliver state (PRD 056 R5, R7)."""
    return dict(_hierarchy_map(state))


def set_hierarchy_map(state: dict[str, Any], hmap: dict[str, Any]) -> None:
    """Persist hierarchyMap on deliver state (additive field only)."""
    state["hierarchyMap"] = hmap


def cmd_ledger_record(root: Path, args: list[str]) -> None:
    task_ref = parse_kv(args, "--task")
    phase_slug = parse_kv(args, "--phase")
    if not task_ref:
        fail("--task required (e.g. 7.1)")
    done = parse_kv(args, "--done", "true") != "false"
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path)
    if not state:
        fail("run state missing; run state init first")
    ledger = _task_ledger(state)
    tasks = ledger["tasks"]
    if not isinstance(tasks, dict):
        tasks = {}
        ledger["tasks"] = tasks
    tasks[task_ref] = {
        "done": done,
        "phase": phase_slug,
        "updatedAt": utc_now(),
    }
    if phase_slug:
        phases = ledger["phases"]
        if isinstance(phases, dict):
            phases.setdefault(phase_slug, {"tasks": [], "updatedAt": utc_now()})
            phase_entry = phases[phase_slug]
            if isinstance(phase_entry, dict):
                refs = phase_entry.setdefault("tasks", [])
                if isinstance(refs, list) and task_ref not in refs:
                    refs.append(task_ref)
                phase_entry["updatedAt"] = utc_now()
    state["taskLedger"] = ledger
    state["updatedAt"] = utc_now()
    write_json(state_path, state)
    append_log(root, {"event": "ledger-record", "task": task_ref, "done": done, "phase": phase_slug})
    emit({"verdict": "pass", "action": "ledger-record", "task": task_ref, "done": done})


def cmd_ledger_check(root: Path, args: list[str]) -> None:
    tasks_file = parse_kv(args, "--tasks-file")
    if not tasks_file:
        fail("--tasks-file required")
    path = (root / tasks_file).resolve() if not Path(tasks_file).is_absolute() else Path(tasks_file)
    if not path.is_file():
        fail(f"tasks file not found: {tasks_file}")
    state_path = _ops_state_path(root, args)
    state = load_state_file(state_path) if state_path.is_file() else {}
    ledger_tasks = ((state.get("taskLedger") or {}).get("tasks") or {}) if state else {}

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import doc_format
    from checkbox_diff import parse_task_checkboxes

    tasks_text = path.read_text(encoding="utf-8")
    phase_id = parse_kv(args, "--phase-id")
    merge_ready = "--merge-ready" in args
    if merge_ready and phase_id:
        phase_refs = parse_task_checkboxes(doc_format.phase_section_text(tasks_text, phase_id))
        if phase_refs:
            all_unchecked = all(not checked for checked in phase_refs.values())
            any_ledger_done = any(
                isinstance(ledger_tasks.get(ref), dict) and ledger_tasks[ref].get("done")
                for ref in phase_refs
            )
            if all_unchecked and not any_ledger_done:
                emit(
                    {
                        "verdict": "fail",
                        "error": "tasks-currency-unchecked-completed-work",
                        "phaseId": phase_id,
                        "refs": sorted(phase_refs.keys()),
                    },
                    exit_code=1,
                )

    checkboxes = parse_task_checkboxes(tasks_text)
    divergences: list[dict[str, Any]] = []

    for ref, checked in checkboxes.items():
        entry = ledger_tasks.get(ref) if isinstance(ledger_tasks, dict) else None
        if not entry:
            if checked:
                divergences.append(
                    {"ref": ref, "kind": "stale", "reason": "checkbox-checked-missing-ledger"}
                )
            continue
        ledger_done = bool(entry.get("done"))
        if ledger_done != checked:
            divergences.append(
                {
                    "ref": ref,
                    "kind": "divergence",
                    "reason": "checkbox-ledger-mismatch",
                    "checkbox": checked,
                    "ledger": ledger_done,
                }
            )

    if isinstance(ledger_tasks, dict):
        for ref, entry in ledger_tasks.items():
            if not isinstance(entry, dict) or not entry.get("done"):
                continue
            if not checkboxes.get(ref, False):
                if not any(d.get("ref") == ref for d in divergences):
                    divergences.append(
                        {"ref": ref, "kind": "stale", "reason": "ledger-done-checkbox-open"}
                    )

    if divergences:
        emit(
            {
                "verdict": "fail",
                "error": "task currency divergence",
                "divergences": divergences,
                "partial": any(d.get("kind") == "stale" for d in divergences),
            },
            exit_code=1,
        )
    emit({"verdict": "pass", "action": "ledger-check", "taskCount": len(checkboxes)})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_state.py <root> <state|lock|journal|log|ledger|resolve|runs> <subcommand> [args...]")
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "resolve":
        if not args:
            fail("resolve subcommand required: state-path|lock-path")
        sub, rest = args[0], args[1:]
        if sub == "state-path":
            cmd_resolve_state_path(root, rest)
        elif sub == "lock-path":
            cmd_resolve_lock_path(root, rest)
        else:
            fail(f"unknown resolve subcommand: {sub}")
    elif domain == "runs":
        if not args or args[0] != "index":
            fail("runs subcommand required: index")
        cmd_runs_index(root, args[1:])
    elif domain == "state":
        if not args:
            fail("state subcommand required: init|get|phase|terminal|heartbeat")
        sub = args[0]
        rest = args[1:]
        if sub == "init":
            cmd_state_init(root, rest)
        elif sub == "get":
            cmd_state_get(root, rest)
        elif sub == "phase":
            cmd_state_phase(root, rest)
        elif sub == "terminal":
            cmd_state_terminal(root, rest)
        elif sub == "heartbeat":
            cmd_state_heartbeat(root, rest)
        else:
            fail(f"unknown state subcommand: {sub}")
    elif domain == "lock":
        if not args:
            fail("lock subcommand required: acquire|release|status")
        sub, rest = args[0], args[1:]
        if sub == "acquire":
            cmd_lock_acquire(root, rest)
        elif sub == "release":
            cmd_lock_release(root, rest)
        elif sub == "status":
            cmd_lock_status(root, rest)
        else:
            fail(f"unknown lock subcommand: {sub}")
    elif domain == "journal":
        if not args:
            fail("journal subcommand required: begin|complete|status")
        sub, rest = args[0], args[1:]
        if sub == "begin":
            cmd_journal_begin(root, rest)
        elif sub == "complete":
            cmd_journal_complete(root, rest)
        elif sub == "status":
            cmd_journal_status(root, rest)
        else:
            fail(f"unknown journal subcommand: {sub}")
    elif domain == "log":
        if not args or args[0] != "tail":
            fail("log subcommand required: tail")
        cmd_log_tail(root, args[1:])
    elif domain == "ledger":
        if not args:
            fail("ledger subcommand required: record|check")
        sub, rest = args[0], args[1:]
        if sub == "record":
            cmd_ledger_record(root, rest)
        elif sub == "check":
            cmd_ledger_check(root, rest)
        else:
            fail(f"unknown ledger subcommand: {sub}")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
