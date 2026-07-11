#!/usr/bin/env python3
"""Merge queue, review barrier, status collection, and terminal report for /sw-deliver.

Concurrency contract (R21/R22/R41): only the conductor calls `merge enqueue` / `merge run-next`.
`merge run-next` authorizes via gate + review barrier, merges onto `<type>/<slug>` never `main`,
and runs single-flight via merge journal + orchestrator lock (`wave_state.py` O_EXCL acquire).

Status collect (R19/R24): reads durable `status.json` only; `blocked` triggers blast-radius apply
on transitive dependents — green siblings in the same wave continue.
"""
from __future__ import annotations

import json
import os
import subprocess

from _sw import interpreter
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_lib import load_workflow_config, remote_name, remote_ref, remote_heads_ref
from wave_json_io import StateCorruptError, read_json, write_json
from wave_state import assert_phase_status
import planning_paths
from _sw.git_integrate import abort_merge, list_merge_conflict_paths, merge_branch_into
from phase_status_discovery import (
    discover_phase_status,
    first_existing_status_path,
    resolve_phase_worktree,
)
from status_integrity import (
    VALID_STATUS_VERDICTS,
    check_status_sha,
    live_host_evidence_ok,
    resolve_pr_number,
    status_is_consumable_terminal,
    validate_terminal_status_shape,
)

PLAN_PATH = Path(".cursor/sw-deliver-plan.json")
FORWARD_MERGE_REBASE_RETRIES = 1

MERGED_TERMINAL_STATUSES = frozenset(
    {"green-merged", "teardown-pending", "teardown-complete"}
)


def load_deliver_plan(root: Path) -> dict[str, Any]:
    path = root / PLAN_PATH
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def phase_id_for_slug(state: dict[str, Any], slug: str) -> str | None:
    for pid, meta in (state.get("phases") or {}).items():
        if isinstance(meta, dict) and meta.get("slug") == slug:
            return str(pid)
    return None


def merged_phase_slugs(state: dict[str, Any]) -> set[str]:
    return {str(r.get("phaseSlug")) for r in (state.get("mergedPhases") or []) if r.get("phaseSlug")}


def dependency_ids_for(phase_id: str, edges: list[dict[str, Any]]) -> list[str]:
    return sorted(str(e.get("from", "")) for e in edges if str(e.get("to", "")) == phase_id)


def topological_sort_slugs(
    slugs: list[str], state: dict[str, Any], edges: list[dict[str, Any]]
) -> list[str]:
    slug_set = set(slugs)
    id_to_slug: dict[str, str] = {}
    for slug in slugs:
        pid = phase_id_for_slug(state, slug)
        if pid:
            id_to_slug[pid] = slug
    in_degree = {s: 0 for s in slugs}
    graph: dict[str, list[str]] = {s: [] for s in slugs}
    for edge in edges:
        from_slug = id_to_slug.get(str(edge.get("from", "")))
        to_slug = id_to_slug.get(str(edge.get("to", "")))
        if from_slug in slug_set and to_slug in slug_set:
            graph[from_slug].append(to_slug)
            in_degree[to_slug] = in_degree.get(to_slug, 0) + 1
    ready = sorted(s for s in slugs if in_degree.get(s, 0) == 0)
    ordered: list[str] = []
    while ready:
        node = ready.pop(0)
        ordered.append(node)
        for nxt in sorted(graph.get(node, [])):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                ready.append(nxt)
                ready.sort()
    for slug in sorted(slugs):
        if slug not in ordered:
            ordered.append(slug)
    return ordered


def reorder_merge_queue(state: dict[str, Any], root: Path) -> None:
    queue = list(state.get("mergeQueue") or [])
    if len(queue) <= 1:
        return
    queue.sort(key=lambda entry: phase_sort_key(state, str(entry.get("phaseSlug", ""))))
    state["mergeQueue"] = queue


def dependencies_merged(phase_id: str, state: dict[str, Any], edges: list[dict[str, Any]]) -> bool:
    merged = merged_phase_slugs(state)
    phases = state.get("phases") or {}
    for dep_id in dependency_ids_for(phase_id, edges):
        dep_meta = phases.get(dep_id) or {}
        dep_slug = str(dep_meta.get("slug") or dep_id)
        if dep_slug not in merged and dep_meta.get("status") not in MERGED_TERMINAL_STATUSES:
            return False
    return True


def select_next_merge_entry(
    state: dict[str, Any], root: Path
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    reorder_merge_queue(state, root)
    queue = list(state.get("mergeQueue") or [])
    if not queue:
        return None, queue
    plan = load_deliver_plan(root)
    edges = plan.get("edges") or []
    merged = merged_phase_slugs(state)
    for entry in queue:
        slug = str(entry.get("phaseSlug", ""))
        pid = phase_id_for_slug(state, slug)
        if pid and not dependencies_merged(pid, state, edges):
            continue
        blocked = False
        for other in queue:
            other_slug = str(other.get("phaseSlug", ""))
            if other_slug == slug:
                break
            if other_slug in merged:
                continue
            if shares_generator_contention(slug, other_slug, plan):
                blocked = True
                break
        if blocked:
            continue
        return entry, queue
    return queue[0], queue


def forward_merge_dependency_branches(
    root: Path,
    state: dict[str, Any],
    phase_slug: str,
    orch_wt: Path,
    target: str,
) -> list[str]:
    """Forward-merge dependency branches into orchestrator worktree before dependent (R8/D7)."""
    pid = phase_id_for_slug(state, phase_slug)
    if not pid:
        return []
    plan = load_deliver_plan(root)
    edges = plan.get("edges") or []
    phases = state.get("phases") or {}
    host_remote = remote_name(load_workflow_config(root))
    git_run(["fetch", host_remote, target], cwd=orch_wt, check=False)
    forward_merged: list[str] = []
    for dep_id in dependency_ids_for(pid, edges):
        dep_meta = phases.get(dep_id) or {}
        dep_slug = str(dep_meta.get("slug") or dep_id)
        dep_branch = dep_meta.get("branch")
        if not dep_branch:
            continue
        if phase_already_merged(orch_wt, str(dep_branch), target):
            continue
        merge_ref = str(dep_branch)
        if git_run(["show-ref", "--verify", f"refs/heads/{dep_branch}"], cwd=orch_wt, check=False).returncode != 0:
            remote_ref_name = remote_heads_ref(host_remote, str(dep_branch))
            if (
                git_run(["show-ref", "--verify", remote_ref_name], cwd=orch_wt, check=False).returncode
                == 0
            ):
                merge_ref = remote_ref(host_remote, str(dep_branch))
            else:
                continue
        proc = git_run(
            [
                "merge",
                "--no-ff",
                merge_ref,
                "-m",
                f"forward-merge(dep): {dep_slug} into {target}",
            ],
            cwd=orch_wt,
            check=False,
        )
        if proc.returncode != 0:
            git_run(["merge", "--abort"], cwd=orch_wt, check=False)
            retried = False
            for _ in range(FORWARD_MERGE_REBASE_RETRIES):
                rebase = git_run(["rebase", merge_ref], cwd=orch_wt, check=False)
                if rebase.returncode == 0:
                    retried = True
                    break
                git_run(["rebase", "--abort"], cwd=orch_wt, check=False)
            if not retried:
                fail(
                    "dependency forward-merge conflict",
                    exit_code=20,
                    halt="blocked",
                    cause="merge-queue:conflict",
                    dependency=dep_slug,
                    phase=phase_slug,
                )
        forward_merged.append(dep_slug)
    return forward_merged


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def fail_payload(data: dict[str, Any], default: str, exit_code: int, **extra: Any) -> None:
    reserved = {"error", *extra.keys()}
    payload = {k: v for k, v in data.items() if k not in reserved}
    fail(data.get("error") or default, exit_code=exit_code, **extra, **payload)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def state_path(root: Path, state: dict[str, Any] | None = None) -> Path:
    from wave_state import resolve_state_path

    return resolve_state_path(root, state_hint=state)


def load_state(root: Path) -> dict[str, Any]:
    from wave_state import load_deliver_state

    return load_deliver_state(root)


def save_state(root: Path, state: dict[str, Any]) -> None:
    from wave_state import save_deliver_state

    save_deliver_state(root, state)


def phase_already_merged(top: Path, phase_branch: str, target: str) -> bool:
    try:
        phase_sha = git_run(["rev-parse", phase_branch], cwd=top, check=True).stdout.strip()
        target_sha = git_run(["rev-parse", target], cwd=top, check=True).stdout.strip()
        proc = git_run(
            ["merge-base", "--is-ancestor", phase_sha, target_sha],
            cwd=top,
            check=False,
        )
        return proc.returncode == 0
    except subprocess.CalledProcessError:
        return False


def clear_open_journal_if_merged(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Idempotent crash recovery: open journal + phase already on target → clear journal (R45)."""
    journal = state.get("mergeJournal")
    if not journal:
        return state
    phase_slug = journal.get("phase", "")
    phases = state.get("phases") or {}
    phase_branch = None
    for meta in phases.values():
        if meta.get("slug") == phase_slug:
            phase_branch = meta.get("branch")
            break
    target = (state.get("target") or {}).get("branch")
    if not phase_branch or not target:
        return state
    top = root
    if phase_already_merged(top, phase_branch, target):
        key = journal.get("key") or phase_slug
        done = list(state.get("completedMerges") or [])
        if not any(isinstance(c, dict) and c.get("key") == key for c in done):
            done.append(
                {
                    "key": key,
                    "phase": phase_slug,
                    "head": journal.get("head"),
                    "completedAt": utc_now(),
                    "recovered": True,
                }
            )
        state["completedMerges"] = done
        state["mergeJournal"] = None
        save_state(root, state)
    return state


DETERMINISTIC_REGEN_RELPATHS = (
    "core/sw-reference/deterministic-regen-paths.json",
    ".sw/deterministic-regen-paths.json",
)
DEFAULT_DETERMINISTIC_CONFLICT_MAX = 1


def deterministic_conflict_max_attempts(root: Path) -> int:
    cfg = load_workflow_config(root)
    deliver = cfg.get("deliver") or {}
    block = deliver.get("deterministicConflict") or {}
    raw = block.get("maxAttempts", DEFAULT_DETERMINISTIC_CONFLICT_MAX)
    try:
        return max(0, min(2, int(raw)))
    except (TypeError, ValueError):
        return DEFAULT_DETERMINISTIC_CONFLICT_MAX


def load_deterministic_regen_config(root: Path) -> dict[str, Any]:
    for rel in DETERMINISTIC_REGEN_RELPATHS:
        path = root / rel
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            continue
    return {"allowlist": list(planning_paths.GENERATOR_OUTPUT_GLOBS)}


def path_in_allowlist(path: str, allowlist: list[str]) -> bool:
    norm = path.replace("\\", "/")
    for entry in allowlist:
        if planning_paths.path_matches_serialized_token(norm, entry):
            return True
        if norm == entry:
            return True
    return False


def paths_within_allowlist(paths: list[str], allowlist: list[str]) -> bool:
    return bool(paths) and all(path_in_allowlist(p, allowlist) for p in paths)




def item_files_for_slug(plan: dict[str, Any], slug: str) -> list[str]:
    for item in plan.get("items") or []:
        if isinstance(item, dict) and item.get("slug") == slug:
            files = item.get("files") or []
            return [str(f) for f in files if f]
    return []


def phase_sort_key(state: dict[str, Any], slug: str) -> tuple[int, str | int]:
    pid = phase_id_for_slug(state, slug)
    if pid and str(pid).isdigit():
        return (0, int(pid))
    return (1, str(pid or slug))


def shares_generator_contention(
    slug_a: str,
    slug_b: str,
    plan: dict[str, Any],
) -> bool:
    files_a = item_files_for_slug(plan, slug_a)
    files_b = item_files_for_slug(plan, slug_b)
    for left in files_a:
        for right in files_b:
            if planning_paths.path_matches_generator_output(left) and planning_paths.path_matches_generator_output(
                right
            ):
                return True
    return False


def conflict_single_preimage(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    conflict_paths: list[str],
    phase_slug: str,
) -> bool:
    allowlist = load_deterministic_regen_config(root).get("allowlist") or []
    contributors: set[str] = set()
    slugs = {phase_slug}
    for entry in state.get("mergeQueue") or []:
        slug = str(entry.get("phaseSlug") or "")
        if slug:
            slugs.add(slug)
    for slug in slugs:
        files = item_files_for_slug(plan, slug)
        touches = any(
            path_in_allowlist(f, allowlist) and any(path_in_allowlist(cp, allowlist) for cp in conflict_paths)
            for f in files
        ) or any(planning_paths.path_matches_generator_output(f) for f in files)
        if not touches:
            continue
        meta = phase_meta_for_slug(state, slug)[1]
        branch = meta.get("branch")
        head = None
        for entry in state.get("mergeQueue") or []:
            if entry.get("phaseSlug") == slug and entry.get("head"):
                head = str(entry.get("head"))
                break
        if not head and branch:
            head = branch
        if head:
            contributors.add(head)
    return len(contributors) <= 1


def regen_output_hash(root: Path, wt: Path, allowlist: list[str]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for rel in sorted(allowlist):
        if rel.endswith("/**"):
            prefix = rel[:-3]
            base = wt / prefix
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    digest.update(str(path.relative_to(wt)).encode("utf-8"))
                    digest.update(path.read_bytes())
        else:
            path = wt / rel
            if path.is_file():
                digest.update(rel.encode("utf-8"))
                digest.update(path.read_bytes())
    return digest.hexdigest()


def stage_allowlisted_outputs(wt: Path, allowlist: list[str]) -> None:
    for entry in allowlist:
        if entry.endswith("/**"):
            prefix = entry[:-3]
            base = wt / prefix
            if not base.is_dir():
                continue
            for path in sorted(base.rglob("*")):
                if path.is_file():
                    rel = str(path.relative_to(wt))
                    git_run(["add", rel], cwd=wt, check=False)
        else:
            path = wt / entry
            if path.is_file():
                git_run(["add", entry], cwd=wt, check=False)


def run_deterministic_regen(root: Path, wt: Path) -> tuple[bool, str]:
    stub = os.environ.get("SW_DETERMINISTIC_REGEN_STUB", "").strip().lower()
    cfg = load_deterministic_regen_config(root)
    allowlist = [str(x) for x in (cfg.get("allowlist") or [])]
    if stub == "pass":
        for entry in allowlist:
            if entry.endswith("/**"):
                continue
            path = wt / entry
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("stub-canonical\n", encoding="utf-8")
        stage_allowlisted_outputs(wt, allowlist)
        return True, "stub-pass"
    if stub == "fail":
        return False, "stub-fail"
    for cmd in cfg.get("regenCommands") or []:
        proc = subprocess.run(cmd, cwd=str(wt), shell=True, text=True, capture_output=True)
        if proc.returncode != 0:
            return False, proc.stderr.strip() or proc.stdout.strip() or f"regen failed: {cmd}"
    stage_allowlisted_outputs(wt, allowlist)
    return True, "regen-commands"


def attempt_deterministic_conflict_resolve(
    root: Path,
    wt: Path,
    state: dict[str, Any],
    conflict_paths: list[str],
    phase_slug: str,
) -> tuple[bool, dict[str, Any]]:
    cfg = load_deterministic_regen_config(root)
    allowlist = [str(x) for x in (cfg.get("allowlist") or [])]
    detail: dict[str, Any] = {"conflictPaths": conflict_paths}
    if not paths_within_allowlist(conflict_paths, allowlist):
        detail["reason"] = "semantic-conflict"
        return False, detail
    plan = load_deliver_plan(root)
    if not conflict_single_preimage(root, state, plan, conflict_paths, phase_slug):
        detail["reason"] = "multi-preimage"
        return False, detail
    attempts = state.setdefault("deterministicConflictAttempts", {})
    key = phase_slug
    count = int(attempts.get(key, 0))
    max_attempts = deterministic_conflict_max_attempts(root)
    if count >= max_attempts:
        detail["reason"] = "deterministic-regen-budget-exhausted"
        detail["attempts"] = count
        return False, detail
    ok, reason = run_deterministic_regen(root, wt)
    if not ok:
        detail["reason"] = reason
        return False, detail
    hash1 = regen_output_hash(root, wt, allowlist)
    ok2, reason2 = run_deterministic_regen(root, wt)
    hash2 = regen_output_hash(root, wt, allowlist)
    if not ok2 or hash1 != hash2:
        detail["reason"] = reason2 or "determinism-gate-failed"
        detail["hash1"] = hash1
        detail["hash2"] = hash2
        return False, detail
    attempts[key] = count + 1
    state["deterministicConflictAttempts"] = attempts
    save_state(root, state)
    detail["reason"] = "deterministic-regen-applied"
    detail["attempt"] = attempts[key]
    return True, detail


def git_run(
    args: list[str],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        check=check,
    )


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = root / "scripts" / "check-gate.py"
    probe = interpreter.probe()
    cmd = [*probe.executable, str(script)]
    if pr:
        cmd.append(pr)
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
    try:
        gate = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        gate = {"verdict": "blocked", "reason": proc.stderr.strip() or "invalid gate output"}
    return proc.returncode, gate


def merge_authorizing(gate_ec: int, gate: dict[str, Any]) -> bool:
    if gate_ec != 0 or gate.get("verdict") != "green":
        return False
    if gate.get("coderabbitLanded") is False:
        return False
    return True


def status_file_for(
    root: Path,
    phase_slug: str,
    explicit: str | None,
    state: dict[str, Any] | None = None,
) -> Path:
    if explicit:
        return Path(explicit).resolve()
    if state is None and state_path(root).is_file():
        state = load_state(root)
    wt = resolve_phase_worktree(root, phase_slug, state or {})
    return first_existing_status_path(
        root, phase_slug, "status.json", worktree=wt
    )


def read_phase_status_optional(
    root: Path,
    phase_slug: str,
    state: dict[str, Any] | None = None,
) -> tuple[Path | None, dict[str, Any] | None]:
    """Re-resolve status via canonical, worktree-local, and glob paths (PRD 027 R6, 036 R14)."""
    if state is None and state_path(root).is_file():
        state = load_state(root)
    state = state or {}
    wt = resolve_phase_worktree(root, phase_slug, state)
    _, meta = phase_meta_for_slug(state, phase_slug)
    phase_branch = meta.get("branch")
    expected_head: str | None = None
    if phase_branch:
        expected_head = phase_branch_head_optional(root, state, phase_slug, str(phase_branch))
    # R8: exact-string SHA equality at read site — reject bad input at write site only.
    return discover_phase_status(
        root,
        phase_slug,
        "status.json",
        worktree=wt,
        expected_head=expected_head,
    )


def phase_meta_for_slug(state: dict[str, Any], phase_slug: str) -> tuple[str | None, dict[str, Any]]:
    for pid, meta in (state.get("phases") or {}).items():
        if isinstance(meta, dict) and meta.get("slug") == phase_slug:
            return str(pid), meta
    return None, {}


def phase_branch_head(root: Path, state: dict[str, Any], phase_slug: str, phase_branch: str) -> str:
    head = phase_branch_head_optional(root, state, phase_slug, phase_branch)
    if not head:
        fail(f"could not resolve head for {phase_branch!r}", phase=phase_slug)
    return head


def phase_branch_head_optional(
    root: Path, state: dict[str, Any], phase_slug: str, phase_branch: str
) -> str | None:
    wt = resolve_phase_worktree(root, phase_slug, state)
    for cwd in (wt, root):
        if cwd is None:
            continue
        proc = git_run(["rev-parse", phase_branch], cwd=cwd, check=False)
        head = proc.stdout.strip()
        if proc.returncode == 0 and head:
            return head
    return None



def validate_status_sha(status: dict[str, Any], expected_head: str, phase_slug: str) -> None:
    # R8: exact-string comparison against git rev-parse HEAD — never relaxed at read site.
    ok, cause = check_status_sha(status, expected_head)
    if not ok:
        fail(
            "stale phase status: head SHA does not match branch tip"
            if cause == "phase-status:stale"
            else "status missing head SHA binding",
            exit_code=20,
            halt="blocked",
            cause=cause,
            phase=phase_slug,
            statusHead=status.get("head"),
            branchHead=expected_head,
        )


def authorize_merge(
    root: Path,
    state: dict[str, Any],
    phase_slug: str,
    entry: dict[str, Any],
    status: dict[str, Any],
    phase_branch: str,
) -> tuple[bool, dict[str, Any], str]:
    expected_head = phase_branch_head(root, state, phase_slug, phase_branch)
    ok_shape, shape_cause = validate_terminal_status_shape(status, root)
    if not ok_shape:
        fail(
            "invalid terminal status",
            exit_code=20,
            halt="blocked",
            cause=shape_cause or "phase-status:invalid",
            phase=phase_slug,
        )
    validate_status_sha(status, expected_head, phase_slug)

    pr_raw = entry.get("pr")
    if pr_raw is not None and str(pr_raw).strip() not in ("", "null", "None"):
        pr_number = int(pr_raw)
    else:
        pr_number = resolve_pr_number(root, state, phase_slug, status, phase_branch)
    authorized, evidence = live_host_evidence_ok(root, status, expected_head, pr_number)
    auth_path = str(evidence.get("authPath") or ("pr" if pr_number is not None else "local"))
    return authorized, evidence, auth_path




def reconcile_next_action_after_collect(root: Path, state: dict[str, Any]) -> str | None:
    from wave_deliver_loop import compute_next_action, load_plan
    plan = load_plan(root)
    if not plan:
        return None
    next_step = compute_next_action(root, state, plan)
    action = str(next_step.get("action") or "")
    if action:
        state["nextAction"] = action
        save_state(root, state)
    return action or None


def cmd_status_collect(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    state = load_state(root) if state_path(root).is_file() else {}
    path = status_file_for(root, phase_slug, parse_kv(args, "--path"), state)
    if not path.is_file():
        fail(
            f"phase status not found: {path}",
            exit_code=20,
            halt="blocked",
            cause="phase-status:missing",
            phase=phase_slug,
        )
    status = read_json(path)
    verdict = status.get("verdict")
    if verdict not in VALID_STATUS_VERDICTS:
        fail(
            f"invalid phase status verdict: {verdict!r}",
            exit_code=20,
            phase=phase_slug,
        )
    _, meta = phase_meta_for_slug(state, phase_slug)
    phase_branch = meta.get("branch")
    ok_shape, shape_cause = validate_terminal_status_shape(status, root)
    if not ok_shape:
        fail(
            "invalid terminal status",
            exit_code=20,
            halt="blocked",
            cause=shape_cause or "phase-status:invalid",
            phase=phase_slug,
        )
    if phase_branch and verdict == "merge-ready-green":
        expected = phase_branch_head_optional(root, state, phase_slug, str(phase_branch))
        if expected:
            validate_status_sha(status, expected, phase_slug)
    progress_sync = None
    if verdict == "merge-ready-green":
        from planning_progress import sync_phase_done

        run_state = load_state(root)
        collect_phase_id = None
        for pid, meta in (run_state.get("phases") or {}).items():
            if meta.get("slug") == phase_slug:
                collect_phase_id = str(pid)
                break
        if collect_phase_id:
            progress_sync = sync_phase_done(root, run_state, collect_phase_id)
            if progress_sync.get("synced") or progress_sync.get("idempotent"):
                save_state(root, run_state)
        if status_is_consumable_terminal(status):
            run_state = load_state(root)
            reconcile_next_action_after_collect(root, run_state)
    if verdict == "blocked":
        state = load_state(root)
        phases = state.get("phases") or {}
        for pid, meta in phases.items():
            if meta.get("slug") == phase_slug:
                meta["status"] = "blocked"
                meta["updatedAt"] = utc_now()
                if status.get("cause"):
                    meta["cause"] = status["cause"]
                phases[pid] = meta
                break
        state["phases"] = phases
        save_state(root, state)
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "wave_failure.py"),
                str(root),
                "blast-radius",
                "apply",
                "--phase-slug",
                phase_slug,
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
    payload = {
        "verdict": "pass",
        "action": "status-collect",
        "phase": phase_slug,
        "statusPath": str(path),
        "status": status,
    }
    if progress_sync is not None:
        payload["progressSync"] = progress_sync
    if verdict == "merge-ready-green" and status_is_consumable_terminal(status):
        payload["nextActionReconciled"] = load_state(root).get("nextAction")
    emit(payload)


def cmd_phase_dispatch_env(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug")
    if not phase_slug:
        fail("--phase-slug required")
    conductor_mode = parse_kv(args, "--conductor-mode") or "inline"
    run_dir_rel = f".cursor/sw-deliver-runs/{phase_slug}"
    run_dir = root / run_dir_rel
    try:
        from intra_phase_dispatch import stamp_phase_context

        stamp_phase_context(run_dir, conductor_mode)
    except ImportError:
        pass
    from wave_phase_pr import resolve_phase_pr_base
    phase_pr_base = resolve_phase_pr_base(root)
    if phase_pr_base.get("verdict") != "ok":
        fail_payload(phase_pr_base, "phase-pr-base", exit_code=20)
    integration = phase_pr_base.get("integrationBranch") or ""
    emit(
        {
            "verdict": "pass",
            "action": "phase-dispatch-env",
            "phase": phase_slug,
            "conductorMode": conductor_mode,
            "phaseContextPath": str(run_dir / "phase-context.json"),
            "phasePrBase": phase_pr_base,
            "exports": {
                "SW_PHASE_MODE": "1",
                "SW_PHASE_SLUG": phase_slug,
                "SW_RUN_DIR": run_dir_rel,
                "SW_REPO_ROOT": str(root.resolve()),
                "SW_INTEGRATION_BRANCH": integration,
            },
            "invoke": "/sw-ship --phase-mode",
            "note": "Run full /sw-ship chain in phase worktree; orchestrator does not bypass steps",
        }
    )


def cmd_merge_gate_check(root: Path, args: list[str]) -> None:
    pr = parse_kv(args, "--pr")
    gate_ec, gate = run_check_gate(root, pr)
    ready = merge_authorizing(gate_ec, gate)
    payload: dict[str, Any] = {
        "verdict": "pass" if ready else "wait",
        "mergeReady": ready,
        "gate": gate,
        "gateExitCode": gate_ec,
        "reviewBarrierSettled": gate.get("coderabbitLanded") is not False,
    }
    if not ready:
        payload["reason"] = gate.get("reason") or "gate not green or review not settled"
    emit(payload, 0 if ready else 10)


def cmd_merge_enqueue(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    state = load_state(root)
    explicit = parse_kv(args, "--status-path")
    if explicit:
        status_path = Path(explicit).resolve()
        status = read_json(status_path)
    else:
        status_path, status = read_phase_status_optional(root, phase_slug, state)
        if status is None or status_path is None:
            fail(
                "phase status not found for enqueue",
                exit_code=20,
                halt="blocked",
                cause="phase-status:missing",
                phase=phase_slug,
            )
    if status.get("verdict") != "merge-ready-green":
        fail(
            "only merge-ready-green phases may be enqueued",
            exit_code=20,
            status=status,
        )
    _, meta = phase_meta_for_slug(state, phase_slug)
    phase_branch = meta.get("branch")
    if not phase_branch:
        fail("missing phase branch for enqueue", exit_code=20, phase=phase_slug)
    expected = phase_branch_head(root, state, phase_slug, str(phase_branch))
    ok_shape, shape_cause = validate_terminal_status_shape(status, root)
    if not ok_shape:
        fail(
            "invalid terminal status",
            exit_code=20,
            halt="blocked",
            cause=shape_cause or "phase-status:invalid",
            phase=phase_slug,
        )
    validate_status_sha(status, expected, phase_slug)
    entry = {"phaseSlug": phase_slug, "pr": status.get("pr")}
    authorized, evidence, auth_path = authorize_merge(
        root, state, phase_slug, entry, status, str(phase_branch)
    )
    if not authorized:
        fail(
            "live host evidence disagrees with terminal status",
            exit_code=20,
            halt="blocked",
            cause=evidence.get("reason") or "phase-status:live-evidence-mismatch",
            phase=phase_slug,
            evidence=evidence,
            authPath=auth_path,
        )
    queue = list(state.get("mergeQueue") or [])
    if any(item.get("phaseSlug") == phase_slug for item in queue):
        emit({"verdict": "pass", "action": "merge-enqueue", "note": "already queued", "phase": phase_slug})
    entry = {
        "phaseSlug": phase_slug,
        "head": status.get("head"),
        "pr": status.get("pr"),
        "enqueuedAt": utc_now(),
    }
    queue.append(entry)
    state["mergeQueue"] = queue
    reorder_merge_queue(state, root)
    save_state(root, state)
    emit({"verdict": "pass", "action": "merge-enqueue", "entry": entry, "queueLength": len(state["mergeQueue"])})


def resolve_orchestrator_worktree(root: Path, args: list[str]) -> Path:
    explicit = parse_kv(args, "--orchestrator-worktree")
    if explicit:
        return Path(explicit).resolve()
    state = load_state(root)
    orch = state.get("orchestratorWorktree") or {}
    path = orch.get("path")
    if not path:
        fail("orchestrator worktree not provisioned; run orchestrator provision first")
    return Path(path).resolve()


def cmd_merge_exec(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug")
    phase_branch = parse_kv(args, "--phase-branch")
    target = parse_kv(args, "--target")
    if not phase_slug or not phase_branch or not target:
        fail("--phase-slug, --phase-branch, and --target required")
    wt = resolve_orchestrator_worktree(root, args)
    host_remote = remote_name(load_workflow_config(root))
    git_run(["fetch", host_remote, phase_branch, target], cwd=wt, check=False)
    merge_ref = phase_branch
    if git_run(["show-ref", "--verify", f"refs/heads/{phase_branch}"], cwd=wt, check=False).returncode != 0:
        if (
            git_run(
                ["show-ref", "--verify", remote_heads_ref(host_remote, phase_branch)],
                cwd=wt,
                check=False,
            ).returncode
            == 0
        ):
            merge_ref = remote_ref(host_remote, phase_branch)
        else:
            fail(f"phase branch not found: {phase_branch}")

    msg = parse_kv(args, "--message") or f"merge({target.split('/')[-1]}): phase {phase_slug}"
    state = load_state(root)
    merge_result = merge_branch_into(wt, merge_ref, message=msg, abort_on_conflict=False)
    if merge_result.get("verdict") != "pass":
        conflict_paths = list(merge_result.get("conflicts") or [])
        resolved = False
        resolve_detail: dict[str, Any] = {}
        if conflict_paths:
            resolved, resolve_detail = attempt_deterministic_conflict_resolve(
                root, wt, state, conflict_paths, phase_slug
            )
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        if resolved:
            proc = git_run(["commit", "-m", msg], cwd=wt, check=False)
        if not resolved or proc.returncode != 0:
            abort_merge(wt)
            fail_detail = dict(resolve_detail)
            fail_detail.setdefault("conflictPaths", conflict_paths)
            fail(
                "merge failed",
                exit_code=20,
                halt="blocked",
                cause="merge-queue:conflict",
                stderr=str(merge_result.get("stderr") or proc.stderr or "").strip(),
                **fail_detail,
            )
    head = git_run(["rev-parse", "HEAD"], cwd=wt).stdout.strip()
    emit(
        {
            "verdict": "pass",
            "action": "merge-exec",
            "phase": phase_slug,
            "mergeCommit": head,
            "method": "merge",
            "target": target,
        }
    )


def cmd_merge_ancestry_check(root: Path, args: list[str]) -> None:
    phase_branch = parse_kv(args, "--phase-branch")
    target = parse_kv(args, "--target")
    if not phase_branch or not target:
        fail("--phase-branch and --target required")
    top = Path(
        subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    phase_sha = git_run(["rev-parse", phase_branch], cwd=top, check=False).stdout.strip()
    target_sha = git_run(["rev-parse", target], cwd=top, check=False).stdout.strip()
    if not phase_sha or not target_sha:
        fail("could not resolve branch tips")
    proc = git_run(
        ["merge-base", "--is-ancestor", phase_sha, target_sha],
        cwd=top,
        check=False,
    )
    merged = proc.returncode == 0
    emit(
        {
            "verdict": "pass",
            "merged": merged,
            "phaseBranch": phase_branch,
            "target": target,
            "predicate": "git merge-base --is-ancestor <phase-tip> <target-tip>",
        }
    )


def cmd_merge_run_next(root: Path, args: list[str]) -> None:
    dry_run = "--dry-run" in args
    state = load_state(root)
    state = clear_open_journal_if_merged(root, state)
    if state.get("mergeJournal"):
        fail("merge already in flight", exit_code=20, journal=state["mergeJournal"])
    queue = list(state.get("mergeQueue") or [])
    if not queue:
        emit({"verdict": "pass", "action": "merge-run-next", "note": "queue empty"})
    entry, queue = select_next_merge_entry(state, root)
    if entry is None:
        emit({"verdict": "pass", "action": "merge-run-next", "note": "queue empty"})
    if queue and queue[0].get("phaseSlug") != entry.get("phaseSlug"):
        by_slug = {str(e.get("phaseSlug")): e for e in queue}
        slug = str(entry.get("phaseSlug", ""))
        state["mergeQueue"] = [by_slug[slug]] + [e for e in queue if e.get("phaseSlug") != slug]
        save_state(root, state)
        queue = list(state["mergeQueue"])
    phase_slug = entry.get("phaseSlug", "")
    pr = entry.get("pr")
    pr_str = str(pr) if pr is not None else None

    phases = state.get("phases") or {}
    phase_branch = None
    phase_id = None
    for pid, meta in phases.items():
        if meta.get("slug") == phase_slug:
            phase_branch = meta.get("branch")
            phase_id = pid
            break
    target = (state.get("target") or {}).get("branch")
    if not phase_branch or not target:
        fail("missing phase branch or target in run-state")

    status_path = status_file_for(root, phase_slug, None, state)
    if not status_path.is_file():
        fail(
            "phase status missing for merge",
            exit_code=20,
            halt="blocked",
            cause="phase-status:missing",
            phase=phase_slug,
            statusPath=str(status_path),
        )
    status = read_json(status_path)
    authorized, gate, auth_path = authorize_merge(
        root, state, phase_slug, entry, status, str(phase_branch)
    )
    if not authorized:
        fail(
            "review barrier / gate not satisfied",
            exit_code=10,
            halt="wait" if auth_path == "pr" else "blocked",
            gate=gate,
            phase=phase_slug,
            authPath=auth_path,
        )

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "merge-run-next",
                "dry_run": True,
                "phase": phase_slug,
                "phaseBranch": phase_branch,
                "target": target,
                "gate": gate,
                "authPath": auth_path,
            }
        )

    orch_wt = resolve_orchestrator_worktree(root, args)
    forward_merged = forward_merge_dependency_branches(
        root, state, str(phase_slug), orch_wt, str(target)
    )

    journal = {
        "phase": phase_slug,
        "head": status.get("head"),
        "startedAt": utc_now(),
        "key": phase_slug,
    }
    state["mergeJournal"] = journal
    save_state(root, state)

    merge_args = [
        "--phase-slug",
        phase_slug,
        "--phase-branch",
        phase_branch,
        "--target",
        target,
    ]
    orch = parse_kv(args, "--orchestrator-worktree")
    if orch:
        merge_args.extend(["--orchestrator-worktree", orch])

    try:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "wave_merge.py"), str(root), "merge", "exec", *merge_args],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            state = load_state(root)
            state["mergeJournal"] = None
            save_state(root, state)
            try:
                err = json.loads(proc.stdout)
            except json.JSONDecodeError:
                err = {"error": proc.stderr or proc.stdout}
            fail_payload(err, "merge failed", proc.returncode)

        merge_out = json.loads(proc.stdout)
        merge_commit = merge_out.get("mergeCommit")

        state = load_state(root)
        state["mergeQueue"] = queue[1:]
        state["mergeJournal"] = None
        done = list(state.get("completedMerges") or [])
        key = phase_slug
        if not any(isinstance(c, dict) and c.get("key") == key for c in done):
            done.append(
                {
                    "key": key,
                    "phase": phase_slug,
                    "head": None,
                    "completedAt": utc_now(),
                    "mergeCommit": merge_commit,
                }
            )
        state["completedMerges"] = done
        merged = list(state.get("mergedPhases") or [])
        merged.append(
            {
                "phaseSlug": phase_slug,
                "phaseId": phase_id,
                "pr": pr,
                "mergeCommit": merge_commit,
                "mergedAt": utc_now(),
            }
        )
        state["mergedPhases"] = merged
        if phase_id and phase_id in state.get("phases", {}):
            assert_phase_status("teardown-pending")
            state["phases"][phase_id]["status"] = "teardown-pending"
            state["phases"][phase_id]["updatedAt"] = utc_now()
            state["phases"][phase_id]["mergeCommit"] = merge_commit
        save_state(root, state)

        target_branch = (state.get("target") or {}).get("branch", "feat/unknown")
        commit_type = target_branch.split("/", 1)[0] if "/" in target_branch else "feat"
        if phase_id and phase_id in state.get("phases", {}):
            for record in state.get("mergedPhases") or []:
                if record.get("phaseSlug") == phase_slug:
                    record["commitType"] = commit_type
                    break
            save_state(root, state)

        bk_args = [
            sys.executable,
            str(SCRIPT_DIR / "wave_bookkeeping.py"),
            str(root),
            "record",
            "--phase-slug",
            phase_slug,
            "--message",
            f"merge phase {phase_slug} into {target_branch}",
            "--type",
            commit_type,
            "--merge-commit",
            merge_commit or "",
            "--commit",
            "--worktree",
            str(orch_wt),
        ]
        bk_proc = subprocess.run(bk_args, cwd=str(root), text=True, capture_output=True)
        if bk_proc.returncode != 0:
            try:
                err = json.loads(bk_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": bk_proc.stderr or bk_proc.stdout}
            fail(
                err.get("error", "bookkeeping record failed"),
                exit_code=bk_proc.returncode,
                **{k: v for k, v in err.items() if k != "error"},
            )
        bookkeeping = json.loads(bk_proc.stdout)

        living_args = [
            sys.executable,
            str(SCRIPT_DIR / "wave_living_docs.py"),
            str(root),
            "reconcile",
            "--commit",
            "--worktree",
            str(orch_wt),
        ]
        living_proc = subprocess.run(living_args, cwd=str(root), text=True, capture_output=True)
        living_docs = {}
        if living_proc.stdout.strip():
            try:
                living_docs = json.loads(living_proc.stdout)
            except json.JSONDecodeError:
                living_docs = {"raw": living_proc.stdout}
        if living_proc.returncode != 0:
            try:
                err = json.loads(living_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": living_proc.stderr or living_proc.stdout}
            fail(
                err.get("error", "living-docs reconcile failed"),
                exit_code=living_proc.returncode,
                **{k: v for k, v in err.items() if k != "error"},
            )

        verify_args = [
            sys.executable,
            str(SCRIPT_DIR / "wave_failure.py"),
            str(root),
            "verify",
            "run-after-merge",
            "--phase-slug",
            phase_slug,
        ]
        if orch:
            verify_args.extend(["--orchestrator-worktree", orch])
        verify_proc = subprocess.run(verify_args, cwd=str(root), text=True, capture_output=True)
        if verify_proc.returncode != 0:
            try:
                err = json.loads(verify_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": verify_proc.stderr or verify_proc.stdout}
            from wave_failure import classify_verify_failure, verify_failure_cause

            verify_outcome = err.get("verify") if isinstance(err.get("verify"), dict) else err
            cause = str(err.get("cause") or verify_failure_cause(verify_outcome))
            cause_class = classify_verify_failure(verify_outcome)
            if cause == "verify:environmental" or cause_class == "environmental":
                state = load_state(root)
                if phase_id and phase_id in state.get("phases", {}):
                    phase_meta = state["phases"][phase_id]
                    phase_meta["verifyEnvironmental"] = True
                    phase_meta["cause"] = "verify:environmental"
                    phase_meta["updatedAt"] = utc_now()
                save_state(root, state)
                emit(
                    {
                        "verdict": "wait",
                        "action": "merge-run-next",
                        "phase": phase_slug,
                        "verify": verify_outcome,
                        "cause": "verify:environmental",
                        "causeClass": "environmental",
                        "forwardMergedDependencies": forward_merged,
                        "mergeRetained": True,
                        "note": "Environmental post-merge verify — merge retained; bounded remediation (R9)",
                    },
                    exit_code=10,
                )
            fail_payload(
                err,
                "incremental verify failed after merge",
                verify_proc.returncode or 20,
                halt="blocked",
                cause="verify:failed",
                causeClass="regression",
            )
        verify_out = json.loads(verify_proc.stdout)

        ack_proc = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "wave_terminal.py"), str(root), "ack", "record-merge"],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        ack_out = json.loads(ack_proc.stdout) if ack_proc.stdout.strip() else {}

        from wave_phase_pr import close_superseded_phase_prs
        state = load_state(root)
        pr_close = close_superseded_phase_prs(root, state, phase_slug=phase_slug)

        progress_sync = None
        if phase_id:
            from planning_progress import sync_phase_done

            progress_sync = sync_phase_done(root, state, str(phase_id))
            if progress_sync.get("synced") or progress_sync.get("idempotent"):
                save_state(root, state)

        merge_payload = {
                "verdict": "pass",
                "action": "merge-run-next",
                "forwardMergedDependencies": forward_merged,
                "supersededPrClose": pr_close,
                "phase": phase_slug,
                "mergeCommit": merge_commit,
                "remaining": len(state["mergeQueue"]),
                "bookkeeping": bookkeeping,
                "livingDocs": living_docs,
                "verify": verify_out,
                "ack": ack_out,
                "authPath": auth_path,
            }
        if progress_sync is not None:
            merge_payload["progressSync"] = progress_sync
        emit(merge_payload)
    except Exception:
        state = load_state(root)
        state["mergeJournal"] = None
        save_state(root, state)
        raise


def cmd_merge_collect_all_ready(root: Path, args: list[str]) -> None:
    """Enqueue all merge-ready-green phases deterministically (phase-id sort, R27)."""
    slugs_raw = parse_kv(args, "--phase-slugs")
    if not slugs_raw:
        fail("--phase-slugs required (comma-separated)")
    slugs = [s.strip() for s in slugs_raw.split(",") if s.strip()]
    enqueued: list[str] = []
    for slug in sorted(slugs):
        proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "wave_merge.py"),
                str(root),
                "merge",
                "enqueue",
                "--phase-slug",
                slug,
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            try:
                err = json.loads(proc.stdout)
            except json.JSONDecodeError:
                err = {"error": proc.stderr or proc.stdout}
            fail_payload(err, "merge enqueue failed", proc.returncode)
        enqueued.append(slug)
    state = load_state(root)
    reorder_merge_queue(state, root)
    save_state(root, state)
    emit(
        {
            "verdict": "pass",
            "action": "merge-collect-all-ready",
            "enqueued": enqueued,
            "queueLength": len(state.get("mergeQueue") or []),
        }
    )



def cmd_report_terminal(root: Path, args: list[str]) -> None:
    state = load_state(root)
    target = (state.get("target") or {}).get("branch", "")
    phases = state.get("phases") or {}
    merged_phases = list(state.get("mergedPhases") or [])
    blocked = [p for p in phases.values() if p.get("status") == "blocked"]
    pending = [
        p
        for p in phases.values()
        if p.get("status") not in (*MERGED_TERMINAL_STATUSES, "blocked", "rejected")
    ]
    completion = state.get("completion") or {}
    completion_pending = completion.get("status") == "completed-pending-merge"
    all_merged = len(pending) == 0 and len(blocked) == 0 and len(phases) > 0

    phase_prs: list[dict[str, Any]] = []
    for record in merged_phases:
        pr = record.get("pr")
        slug = record.get("phaseSlug")
        url = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', 'owner/repo')}/pull/{pr}" if pr else None
        phase_prs.append(
            {
                "phaseSlug": slug,
                "pr": pr,
                "prUrl": url,
                "mergeCommit": record.get("mergeCommit"),
            }
        )

    report: dict[str, Any] = {
        "verdict": "complete" if all_merged and not completion_pending else ("blocked" if blocked else "running"),
        "targetBranch": target,
        "phasePrs": phase_prs,
        "blockedPhases": [{"slug": p.get("slug"), "cause": p.get("cause")} for p in blocked],
        "conventionalCommitTypes": ["feat", "fix", "perf", "revert", "docs", "chore", "refactor", "test"],
    }
    if completion_pending:
        report["completionPendingMerge"] = True
        report["note"] = (
            "Pre-merge compounding recorded; awaiting human merge — not complete until merged (R53)"
        )
    from wave_phase_pr import close_superseded_phase_prs
    pr_close = close_superseded_phase_prs(root, state)
    report["supersededPrClose"] = pr_close

    if all_merged and not state.get("terminalRejected") and not completion_pending:
        report["terminalGate"] = "ready to merge — your call"
        report["note"] = "Open or update single <type>/<slug> → main PR; halt without merging"
        terminal = state.get("terminalPr") or {}
        pr_num = terminal.get("number")
        if pr_num is not None:
            report["terminalPr"] = terminal
            gate_ec, gate = run_check_gate(root, str(pr_num))
            report["gate"] = gate
            report["gateExitCode"] = gate_ec
            if gate_ec == 0 and gate.get("verdict") == "green":
                report["gateVerdict"] = "green"
            else:
                report["gateVerdict"] = gate.get("verdict", "blocked")
    elif state.get("terminalRejected"):
        report["terminalRejected"] = True
        report["note"] = "Terminal PR rejected; resume must not re-present (R46)"
    from deliver_plan_surfacing import REPORT_KIND_TERMINAL, attach_plan_surfacing_to_report
    import planning_unit_status as pus

    handoff = pus.deliver_handoff_paths(root, state)
    if handoff:
        report["handoff"] = handoff
        report["resumeCommand"] = handoff["resumeCommand"]
    attach_plan_surfacing_to_report(root, state, report, report_kind=REPORT_KIND_TERMINAL)
    emit({"verdict": "pass", "action": "report-terminal", "report": report})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_merge.py <root> <domain> <subcommand> [args...]")
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "status":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "collect":
            cmd_status_collect(root, rest)
        else:
            fail("status subcommand required: collect")
    elif domain == "phase":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "dispatch-env":
            cmd_phase_dispatch_env(root, rest)
        else:
            fail("phase subcommand required: dispatch-env")
    elif domain == "merge":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "gate-check":
            cmd_merge_gate_check(root, rest)
        elif sub == "enqueue":
            cmd_merge_enqueue(root, rest)
        elif sub == "exec":
            cmd_merge_exec(root, rest)
        elif sub == "run-next":
            cmd_merge_run_next(root, rest)
        elif sub == "collect-all-ready":
            cmd_merge_collect_all_ready(root, rest)
        elif sub == "ancestry-check":
            cmd_merge_ancestry_check(root, rest)
        else:
            fail("merge subcommand required: gate-check|enqueue|exec|run-next|collect-all-ready|ancestry-check")
    elif domain == "report":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "terminal":
            cmd_report_terminal(root, rest)
        else:
            fail("report subcommand required: terminal")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
