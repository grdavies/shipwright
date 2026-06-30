#!/usr/bin/env python3
"""Verify, blast-radius, revert/unstack, stabilize routing for /sw-deliver (R25–R27, R39, R45–R46)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
FLAKY_DEFAULT_RETRIES = 1

ENVIRONMENTAL_VERIFY_MARKERS = (
    "cursor-golden-vs-dist",
    "run-parity-fixtures",
    "emitter freshness",
    "build-chain-sync",
    "build-chain-sync --check",
    "parallelceiling",
    "parallel ceiling",
    "parallel_ceiling",
    "fixture-harness",
    "harness unavailable",
    "harness-unavailable",
    "no verify commands configured",
)


def classify_verify_failure(outcome: dict[str, Any]) -> str:
    """Return cause class: environmental | regression (R9)."""
    note = str(outcome.get("note") or "").lower()
    if "no verify commands configured" in note:
        return "environmental"
    for result in outcome.get("results") or []:
        blob = " ".join(
            str(result.get(k) or "") for k in ("command", "stdoutTail", "stderrTail")
        ).lower()
        if any(marker in blob for marker in ENVIRONMENTAL_VERIFY_MARKERS):
            return "environmental"
    return "regression"


def verify_failure_cause(outcome: dict[str, Any]) -> str:
    if classify_verify_failure(outcome) == "environmental":
        return "verify:environmental"
    return "verify:failed"


def remediation_max_attempts(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    remediation = deliver.get("remediation") or {}
    try:
        return max(0, int(remediation.get("maxAttempts", 2)))
    except (TypeError, ValueError):
        return 2


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def state_path(root: Path, state: dict[str, Any] | None = None) -> Path:
    from wave_state import resolve_state_path

    return resolve_state_path(root, state_hint=state)


def load_state(root: Path) -> dict[str, Any]:
    from wave_state import load_deliver_state

    return load_deliver_state(root)


def save_state(root: Path, state: dict[str, Any]) -> None:
    from wave_state import save_deliver_state

    save_deliver_state(root, state)


def load_plan(root: Path) -> dict[str, Any]:
    plan_path = root / ".cursor" / "sw-deliver-plan.json"
    if not plan_path.is_file():
        fail("deliver plan missing: .cursor/sw-deliver-plan.json")
    return json.loads(plan_path.read_text(encoding="utf-8"))


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def plan_edges(root: Path) -> list[dict[str, str]]:
    plan = load_plan(root)
    return [dict(e) for e in plan.get("edges") or []]


def adjacency(edges: list[dict[str, str]]) -> dict[str, list[str]]:
    adj: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        adj[str(edge["from"])].append(str(edge["to"]))
    return adj


def transitive_dependent_ids(source_id: str, edges: list[dict[str, str]]) -> list[str]:
    adj = adjacency(edges)
    seen: set[str] = set()
    queue: deque[str] = deque(adj.get(source_id, []))
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(adj.get(node, []))
    return sorted(seen, key=lambda x: (0, int(x)) if x.isdigit() else (1, x))


def find_phase(
    state: dict[str, Any], phase_id: str | None, slug: str | None
) -> tuple[str, dict[str, Any]]:
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
    fail("--phase-id or --phase-slug required")


def resolve_orchestrator_worktree(root: Path, args: list[str]) -> Path:
    explicit = parse_kv(args, "--orchestrator-worktree") or parse_kv(args, "--worktree")
    if explicit:
        return Path(explicit).resolve()
    state = load_state(root)
    orch = state.get("orchestratorWorktree") or {}
    path = orch.get("path")
    if not path:
        fail("orchestrator worktree not provisioned")
    return Path(path).resolve()


def append_log(root: Path, entry: dict[str, Any]) -> None:
    log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
    os.chmod(log_path, 0o600)


def verify_commands(root: Path) -> list[str]:
    cfg = load_workflow_config(root)
    verify = cfg.get("verify") or {}
    if verify.get("test"):
        return [str(verify["test"])]
    cmds: list[str] = []
    for key in ("lint", "typecheck", "test"):
        if verify.get(key):
            cmds.append(str(verify[key]))
    return cmds


def run_verify_suite(
    root: Path, cwd: Path, flaky_retries: int = FLAKY_DEFAULT_RETRIES
) -> dict[str, Any]:
    commands = verify_commands(root)
    if not commands:
        return {
            "verdict": "pass",
            "note": "no verify commands configured",
            "attempts": 0,
            "results": [],
        }
    attempts = flaky_retries + 1
    last_results: list[dict[str, Any]] = []
    for attempt in range(1, attempts + 1):
        last_results = []
        all_ok = True
        for cmd in commands:
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=str(cwd),
                text=True,
                capture_output=True,
            )
            last_results.append(
                {
                    "command": cmd,
                    "exitCode": proc.returncode,
                    "stdoutTail": (proc.stdout or "")[-500:],
                    "stderrTail": (proc.stderr or "")[-500:],
                }
            )
            if proc.returncode != 0:
                all_ok = False
        if all_ok:
            return {
                "verdict": "pass",
                "attempts": attempt,
                "flaky": attempt > 1,
                "results": last_results,
            }
    return {
        "verdict": "fail",
        "attempts": attempts,
        "flakyExhausted": True,
        "results": last_results,
    }


def cmd_verify_run(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    flaky_retries = int(parse_kv(args, "--flaky-retries", str(FLAKY_DEFAULT_RETRIES)) or "1")
    wt = resolve_orchestrator_worktree(root, args)
    target = (load_state(root).get("target") or {}).get("branch", "")
    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "verify-run",
                "dry_run": True,
                "worktree": str(wt),
                "target": target,
                "commands": verify_commands(root),
            }
        )
    outcome = run_verify_suite(root, wt, flaky_retries=flaky_retries)
    payload: dict[str, Any] = {
        "verdict": "pass" if outcome["verdict"] == "pass" else "fail",
        "action": "verify-run",
        "target": target,
        "worktree": str(wt),
        **outcome,
    }
    if outcome["verdict"] != "pass":
        payload["halt"] = "blocked"
        payload["cause"] = verify_failure_cause(outcome)
        payload["causeClass"] = classify_verify_failure(outcome)
        payload["recommendedCommand"] = "/sw-stabilize"
        emit(payload, exit_code=20)
    emit(payload)


def cmd_verify_run_after_merge(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    if has_flag(args, "--dry-run"):
        cmd_verify_run(root, args)
    outcome = run_verify_suite(
        root,
        resolve_orchestrator_worktree(root, args),
        flaky_retries=int(parse_kv(args, "--flaky-retries", str(FLAKY_DEFAULT_RETRIES)) or "1"),
    )
    if outcome["verdict"] == "pass":
        emit(
            {
                "verdict": "pass",
                "action": "verify-run-after-merge",
                "phase": phase_slug,
                **outcome,
            }
        )
    cause = verify_failure_cause(outcome)
    cause_class = classify_verify_failure(outcome)
    if cause == "verify:environmental":
        state = load_state(root)
        pid, _meta = find_phase(state, None, phase_slug)
        attempts_map = state.setdefault("verifyRemediationAttempts", {})
        count = int(attempts_map.get(pid, 0))
        max_attempts = remediation_max_attempts(root)
        if count < max_attempts:
            attempts_map[pid] = count + 1
            save_state(root, state)
            emit(
                {
                    "verdict": "wait",
                    "action": "verify-run-after-merge",
                    "phase": phase_slug,
                    "verify": outcome,
                    "cause": cause,
                    "causeClass": cause_class,
                    "attempt": count + 1,
                    "maxAttempts": max_attempts,
                    "mergeRetained": True,
                    "note": "Environmental post-merge verify — merge retained; bounded remediation (R9)",
                },
                exit_code=10,
            )
    state = load_state(root)
    pid, _meta = find_phase(state, None, phase_slug)
    phase_meta = state["phases"][pid]
    phase_meta["status"] = "blocked"
    phase_meta["cause"] = cause
    phase_meta["updatedAt"] = utc_now()
    history = phase_meta.setdefault("remediationCauseHistory", [])
    if not isinstance(history, list):
        history = []
        phase_meta["remediationCauseHistory"] = history
    history.append(cause)
    phase_meta["lastRemediationCause"] = cause
    save_state(root, state)
    blast_args = ["blast-radius", "apply", "--phase-slug", phase_slug]
    subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_failure.py"), str(root), *blast_args],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    emit(
        {
            "verdict": "fail",
            "action": "verify-run-after-merge",
            "phase": phase_slug,
            "verify": outcome,
            "halt": "blocked",
            "cause": cause,
            "causeClass": cause_class,
            "recommendedCommand": "/sw-stabilize",
            "note": "merge retained; no automatic revert (R26)",
        },
        exit_code=20,
    )


def cmd_blast_radius_dependents(root: Path, args: list[str]) -> None:
    state = load_state(root)
    pid, meta = find_phase(state, parse_kv(args, "--phase-id"), parse_kv(args, "--phase-slug"))
    deps = transitive_dependent_ids(pid, plan_edges(root))
    phases = state.get("phases") or {}
    slugs = [phases[d].get("slug", d) for d in deps if d in phases]
    emit(
        {
            "verdict": "pass",
            "action": "blast-radius-dependents",
            "sourcePhaseId": pid,
            "sourcePhaseSlug": meta.get("slug"),
            "dependentPhaseIds": deps,
            "dependentPhaseSlugs": slugs,
        }
    )


def cmd_blast_radius_apply(root: Path, args: list[str]) -> None:
    state = load_state(root)
    pid, meta = find_phase(state, parse_kv(args, "--phase-id"), parse_kv(args, "--phase-slug"))
    cause = parse_kv(args, "--cause") or meta.get("cause") or "blocked"
    upstream_slug = meta.get("slug", pid)
    deps = transitive_dependent_ids(pid, plan_edges(root))
    phases = state.get("phases") or {}
    blocked: list[dict[str, str]] = []
    for dep_id in deps:
        if dep_id not in phases:
            continue
        if phases[dep_id].get("status") in ("green-merged", "rejected"):
            continue
        phases[dep_id]["status"] = "blocked"
        phases[dep_id]["cause"] = f"blast-radius:upstream-blocked:{upstream_slug}"
        phases[dep_id]["updatedAt"] = utc_now()
        blocked.append(
            {"phaseId": dep_id, "phaseSlug": phases[dep_id].get("slug", dep_id)}
        )
    state["phases"] = phases
    save_state(root, state)
    append_log(
        root,
        {
            "event": "blast-radius",
            "sourcePhaseId": pid,
            "sourcePhaseSlug": upstream_slug,
            "blockedDependents": blocked,
            "cause": cause,
        },
    )
    emit(
        {
            "verdict": "pass",
            "action": "blast-radius-apply",
            "sourcePhaseId": pid,
            "sourcePhaseSlug": upstream_slug,
            "blockedDependents": blocked,
        }
    )


def stabilize_command_for_phase(meta: dict[str, Any], target: str) -> str:
    branch = meta.get("branch") or target
    return f"/sw-stabilize  # phase branch {branch}"


def resume_deliver_command(state: dict[str, Any]) -> str:
    task_list = state.get("source_task_list")
    if task_list:
        return f"/sw-deliver run {task_list}"
    return "/sw-deliver run"

def cmd_stabilize_route(root: Path, args: list[str]) -> None:
    state = load_state(root)
    target = (state.get("target") or {}).get("branch", "")
    scope = parse_kv(args, "--scope", "phase") or "phase"
    if scope == "whole-feature":
        emit(
            {
                "verdict": "pass",
                "action": "stabilize-route",
                "scope": "whole-feature",
                "branch": target,
                "recommendedCommand": f"/sw-stabilize  # target {target}",
                "note": "Distinct whole-feature stabilize budget (R27)",
            }
        )
    pid, meta = find_phase(state, parse_kv(args, "--phase-id"), parse_kv(args, "--phase-slug"))
    emit(
        {
            "verdict": "pass",
            "action": "stabilize-route",
            "scope": "phase",
            "phaseId": pid,
            "phaseSlug": meta.get("slug"),
            "branch": meta.get("branch"),
            "cause": meta.get("cause"),
            "recommendedCommand": stabilize_command_for_phase(meta, target),
            "note": "Per-phase stabilize budget obeys dispatch hard stops (R27)",
        }
    )


def cmd_report_blockers(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    phases = state.get("phases") or {}
    target = (state.get("target") or {}).get("branch", "")
    blockers: list[dict[str, Any]] = []
    blocked_dependents: list[dict[str, str]] = []
    merged_green: list[dict[str, str]] = []
    continuing: list[dict[str, str]] = []

    for pid, meta in phases.items():
        status = meta.get("status")
        slug = meta.get("slug", pid)
        entry = {"phaseId": pid, "phaseSlug": slug, "status": status, "cause": meta.get("cause")}
        if status == "green-merged":
            merged_green.append(entry)
        elif status == "blocked":
            if (meta.get("cause") or "").startswith("blast-radius:"):
                blocked_dependents.append(entry)
            else:
                cause = str(meta.get("cause") or "")
                blockers.append(
                    {
                        **entry,
                        "causeClass": (
                            "environmental"
                            if cause.startswith("verify:environmental")
                            else "regression"
                            if cause.startswith("verify:")
                            else "operational"
                        ),
                        "recommendedCommand": stabilize_command_for_phase(meta, target),
                    }
                )
        elif status in ("pending", "in-flight"):
            continuing.append(entry)

    report = {
        "verdict": "halt" if blockers or blocked_dependents else "running",
        "targetBranch": target,
        "blockers": blockers,
        "blockedDependents": blocked_dependents,
        "mergedGreenThisRun": merged_green,
        "siblingsContinuing": continuing,
        "terminalRejected": bool(state.get("terminalRejected")),
        "resumeCommand": resume_deliver_command(state),
    }
    if state.get("terminalRejected"):
        report["note"] = "Terminal PR rejected; resume must not re-present (R46)"
    from deliver_plan_surfacing import REPORT_KIND_HALT, attach_plan_surfacing_to_report

    attach_plan_surfacing_to_report(root, state, report, report_kind=REPORT_KIND_HALT)
    append_log(root, {"event": "blocker-report", "blockerCount": len(blockers)})
    emit({"verdict": "pass", "action": "report-blockers", "report": report})


def merge_record_for_slug(state: dict[str, Any], phase_slug: str) -> dict[str, Any] | None:
    for record in state.get("mergedPhases") or []:
        if record.get("phaseSlug") == phase_slug and not record.get("reverted"):
            return record
    return None


def cmd_revert_phase(root: Path, args: list[str]) -> None:
    phase_slug = parse_kv(args, "--phase-slug") or parse_kv(args, "--phase")
    if not phase_slug:
        fail("--phase-slug required")
    dry_run = has_flag(args, "--dry-run")
    cause = parse_kv(args, "--cause", "revert:bad-merge") or "revert:bad-merge"
    state = load_state(root)
    pid, meta = find_phase(state, None, phase_slug)
    record = merge_record_for_slug(state, phase_slug)
    merge_commit = (record or {}).get("mergeCommit") or meta.get("mergeCommit")
    if not merge_commit:
        fail(f"no merge commit recorded for phase {phase_slug!r}")

    wt = resolve_orchestrator_worktree(root, args)
    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "revert-phase",
                "dry_run": True,
                "phase": phase_slug,
                "mergeCommit": merge_commit,
                "worktree": str(wt),
            }
        )

    proc = subprocess.run(
        ["git", "revert", "-m", "1", merge_commit, "--no-edit"],
        cwd=str(wt),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(
            "git revert failed",
            exit_code=20,
            stderr=proc.stderr.strip(),
            stdout=proc.stdout.strip(),
        )
    revert_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(wt),
        text=True,
        capture_output=True,
    ).stdout.strip()

    bk_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_bookkeeping.py"),
            str(root),
            "revert",
            "--phase-slug",
            phase_slug,
            "--worktree",
            str(wt),
            "--commit",
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    bookkeeping = {}
    if bk_proc.stdout.strip():
        try:
            bookkeeping = json.loads(bk_proc.stdout)
        except json.JSONDecodeError:
            bookkeeping = {"error": bk_proc.stderr or bk_proc.stdout}

    state = load_state(root)
    state["phases"][pid]["status"] = "blocked"
    state["phases"][pid]["cause"] = cause
    state["phases"][pid]["updatedAt"] = utc_now()
    state["phases"][pid]["revertedAt"] = utc_now()
    state["phases"][pid]["revertCommit"] = revert_sha
    for rec in state.get("mergedPhases") or []:
        if rec.get("phaseSlug") == phase_slug:
            rec["reverted"] = True
            rec["revertCommit"] = revert_sha
    save_state(root, state)

    br_args = ["blast-radius", "apply", "--phase-slug", phase_slug, "--cause", cause]
    orch = parse_kv(args, "--orchestrator-worktree") or parse_kv(args, "--worktree")
    if orch:
        br_args.extend(["--orchestrator-worktree", orch])
    br_proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_failure.py"), str(root), *br_args],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    blast = json.loads(br_proc.stdout) if br_proc.stdout.strip() else {}

    append_log(
        root,
        {
            "event": "phase-revert",
            "phaseSlug": phase_slug,
            "mergeCommit": merge_commit,
            "revertCommit": revert_sha,
            "cause": cause,
        },
    )
    emit(
        {
            "verdict": "pass",
            "action": "revert-phase",
            "phase": phase_slug,
            "mergeCommit": merge_commit,
            "revertCommit": revert_sha,
            "bookkeeping": bookkeeping,
            "blastRadius": blast,
            "recommendedCommand": stabilize_command_for_phase(meta, (state.get("target") or {}).get("branch", "")),
        }
    )


def cmd_terminal_deny(root: Path, args: list[str]) -> None:
    scope = parse_kv(args, "--scope", "whole-feature") or "whole-feature"
    phase_slug = parse_kv(args, "--phase-slug")
    reason = parse_kv(args, "--reason", "human-rejected") or "human-rejected"
    state = load_state(root)
    state["terminalRejected"] = True
    state["terminalRejectedAt"] = utc_now()
    state["terminalRejectScope"] = scope
    state["terminalRejectReason"] = reason
    state["verdict"] = "rejected"
    if scope == "per-phase":
        if not phase_slug:
            fail("--phase-slug required when --scope per-phase")
        subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "wave_failure.py"),
                str(root),
                "revert",
                "phase",
                "--phase-slug",
                phase_slug,
                "--cause",
                "terminal-deny:per-phase",
            ]
            + (
                ["--orchestrator-worktree", parse_kv(args, "--orchestrator-worktree")]
                if parse_kv(args, "--orchestrator-worktree")
                else []
            ),
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        state = load_state(root)
        state["terminalRejected"] = True
        state["verdict"] = "rejected"
    target = (state.get("target") or {}).get("branch", "")
    state["recommendedCommand"] = (
        f"/sw-stabilize  # target {target}"
        if scope == "whole-feature"
        else f"/sw-amend  # per-phase deny on {phase_slug}"
    )
    save_state(root, state)
    append_log(root, {"event": "terminal-deny", "scope": scope, "reason": reason})
    emit(
        {
            "verdict": "pass",
            "action": "terminal-deny",
            "scope": scope,
            "reason": reason,
            "recommendedCommand": state["recommendedCommand"],
            "note": "Resume must not re-present rejected terminal PR (R46)",
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_failure.py <root> <domain> <subcommand> [args...]")
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "verify":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "run":
            cmd_verify_run(root, rest)
        elif sub == "run-after-merge":
            cmd_verify_run_after_merge(root, rest)
        else:
            fail("verify subcommand required: run|run-after-merge")
    elif domain == "blast-radius":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "apply":
            cmd_blast_radius_apply(root, rest)
        elif sub == "dependents":
            cmd_blast_radius_dependents(root, rest)
        else:
            fail("blast-radius subcommand required: apply|dependents")
    elif domain == "report":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "blockers":
            cmd_report_blockers(root, rest)
        else:
            fail("report subcommand required: blockers")
    elif domain == "revert":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "phase":
            cmd_revert_phase(root, rest)
        else:
            fail("revert subcommand required: phase")
    elif domain == "terminal":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "deny":
            cmd_terminal_deny(root, rest)
        else:
            fail("terminal subcommand required: deny")
    elif domain == "stabilize":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "route":
            cmd_stabilize_route(root, rest)
        else:
            fail("stabilize subcommand required: route")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
