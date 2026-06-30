#!/usr/bin/env python3
"""Terminal PR gate, idempotent resume, and phase ack cadence for /sw-deliver (R22–R24, R29–R30, R43, R56)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_invoke import host_verb
from host_lib import load_workflow_config, remote_name, remote_ref, resolve_provider
from wave_state import phase_complete


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: Any, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": str(error), **extra}, exit_code)


def commitlint_safe_title(commit_type: str, slug: str, prd_number: str | None = None) -> str:
    """Conventional-commit title with lowercase prd scope (R43)."""
    if prd_number:
        num = str(prd_number).lstrip("0") or "0"
        scope = f"prd-{num}".lower()
        return f"{commit_type}({scope}): deliver wave"
    safe_slug = slug.lower().replace("_", "-")
    return f"{commit_type}({safe_slug}): deliver wave"


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


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
    return {}


def phase_ack_cadence(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    try:
        return max(0, int(deliver.get("phaseAckCadence", 0)))
    except (TypeError, ValueError):
        return 0


def terminal_autonomy_mode(root: Path) -> str:
    deliver = load_workflow_config(root).get("deliver") or {}
    terminal = deliver.get("terminal") or {}
    mode = terminal.get("autonomy", "supervised")
    return mode if mode in ("supervised", "auto") else "supervised"


def remediation_max_attempts(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    remediation = deliver.get("remediation") or {}
    try:
        return max(0, int(remediation.get("maxAttempts", 2)))
    except (TypeError, ValueError):
        return 2


def current_branch_name(root: Path) -> str:
    proc = git_run(["branch", "--show-current"], cwd=git_top(root), check=False)
    return (proc.stdout or "").strip()


def run_retrospective_record_premerge(root: Path, state: dict[str, Any]) -> None:
    """Record pre-merge retrospective completion on feature branch (R20/R21)."""
    prd = str(state.get("prd_number") or "000").zfill(3)
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_compound.py"),
            str(root),
            "retrospective",
            "record-premerge",
            "--prd",
            prd,
            "--phase",
            "deliver-terminal",
            "--skip-append-log",
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout)
        except json.JSONDecodeError:
            err = {"error": proc.stderr.strip() or proc.stdout.strip()}
        fail(err.get("error", "retrospective record-premerge failed"), exit_code=proc.returncode)




def cmd_terminal_checkpoint(root: Path, args: list[str]) -> None:
    """Single consolidated supervised terminal checkpoint (R10)."""
    dry_run = has_flag(args, "--dry-run")
    state = load_state(root)
    mode = terminal_autonomy_mode(root)
    if not all_phases_green(state):
        fail("terminal checkpoint requires all phases complete", exit_code=20)
    compound = state.get("compoundShip") or {}
    terminal_ship = state.get("terminalShip") or {}
    needs_retro = not compound.get("premergeDone")
    needs_ship = terminal_ship.get("status") not in ("gate-green", "local-evidence")
    if mode == "auto" or has_flag(args, "--force"):
        if dry_run:
            emit(
                {
                    "verdict": "pass",
                    "action": "terminal-checkpoint",
                    "dry_run": True,
                    "mode": mode,
                    "wouldRunRetrospective": needs_retro,
                    "wouldRunTerminalShip": needs_ship,
                }
            )
        if needs_retro:
            cmd_terminal_retro_run(root, ["--force"])
            state = load_state(root)
        if needs_ship:
            cmd_terminal_ship_run(root, ["--force"])
        state = load_state(root)
        state["terminalCheckpointCompleted"] = True
        save_state(root, state)
        emit(
            {
                "verdict": "pass",
                "action": "terminal-checkpoint",
                "mode": mode,
                "completed": True,
            }
        )
    invoke: list[str] = []
    if needs_retro:
        invoke.append("/sw-retrospective --pre-merge")
    if needs_ship:
        invoke.append("/sw-ship")
    emit(
        {
            "verdict": "halt",
            "action": "terminal-checkpoint",
            "halt": "supervised-checkpoint",
            "mode": mode,
            "invoke": invoke,
            "reportTerminal": "bash scripts/wave.sh report terminal",
            "note": "Single consolidated terminal checkpoint — retrospective and ship gate combined (R10)",
        },
        exit_code=11,
    )


def cmd_terminal_autonomy(root: Path, _args: list[str]) -> None:
    mode = terminal_autonomy_mode(root)
    emit(
        {
            "verdict": "pass",
            "action": "terminal-autonomy",
            "mode": mode,
            "handsOff": mode == "auto",
            "supervisedHalts": mode == "supervised",
            "default": "supervised",
        }
    )


def cmd_terminal_retro_run(root: Path, args: list[str]) -> None:
    """Pre-merge retrospective chain before terminal PR (PRD 013 A1 R20/R21)."""
    dry_run = has_flag(args, "--dry-run")
    state = load_state(root)
    if not all_phases_green(state):
        fail("retrospective requires all phases green-merged", exit_code=20)
    target = (state.get("target") or {}).get("branch")
    if not target:
        fail("target branch missing in run-state")
    top = git_top(root)
    default = default_base_branch(root)
    branch = current_branch_name(top)
    if branch == default:
        fail(
            "retrospective artifacts must be committed on feature branch, never main",
            exit_code=20,
            halt="blocked",
            cause="terminal-retro:on-main",
        )
    mode = terminal_autonomy_mode(root)
    if mode == "supervised" and not has_flag(args, "--force"):
        emit(
            {
                "verdict": "halt",
                "action": "terminal-retro-run",
                "halt": "supervised-checkpoint",
                "mode": mode,
                "invoke": "/sw-retrospective --pre-merge",
                "note": "Set deliver.terminal.autonomy: auto for hands-off retrospective",
            },
            exit_code=11,
        )
    if (state.get("compoundShip") or {}).get("premergeDone"):
        emit(
            {
                "verdict": "pass",
                "action": "terminal-retro-run",
                "skipped": True,
                "reason": "premerge already recorded",
            }
        )
    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "terminal-retro-run",
                "dry_run": True,
                "targetBranch": target,
                "wouldCommitOn": branch,
            }
        )
    append_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "wave_living_docs.py"),
            str(root),
            "append-terminal",
            "--commit",
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if append_proc.returncode not in (0, 10):
        try:
            err = json.loads(append_proc.stdout)
        except json.JSONDecodeError:
            err = {"error": append_proc.stderr or append_proc.stdout}
        fail(err.get("error", "living-docs append-terminal failed"), exit_code=append_proc.returncode)
    run_retrospective_record_premerge(root, state)
    state = load_state(root)
    append_log(root, {"event": "terminal-retro-run", "target": target, "branch": branch})
    emit(
        {
            "verdict": "pass",
            "action": "terminal-retro-run",
            "targetBranch": target,
            "committedOn": branch,
            "premergeDone": bool((state.get("compoundShip") or {}).get("premergeDone")),
            "safetyGates": {
                "memoryFailClosed": True,
                "ruleClassHumanGated": True,
            },
        }
    )


def cmd_terminal_ship_run(root: Path, args: list[str]) -> None:
    """Autonomous terminal PR → push → gate watch → stabilize budget (R22/R23)."""
    dry_run = has_flag(args, "--dry-run")
    state = load_state(root)
    mode = terminal_autonomy_mode(root)
    if mode == "supervised" and not has_flag(args, "--force"):
        emit(
            {
                "verdict": "halt",
                "action": "terminal-ship-run",
                "halt": "supervised-checkpoint",
                "mode": mode,
                "note": "Set deliver.terminal.autonomy: auto for hands-off terminal ship",
            },
            exit_code=11,
        )
    if not all_phases_green(state):
        fail("terminal-ship requires all phases green-merged", exit_code=20)
    compound = state.get("compoundShip") or {}
    if not compound.get("premergeDone"):
        cmd_terminal_retro_run(root, ["--force"])
        state = load_state(root)
    target = (state.get("target") or {}).get("branch")
    if not target:
        fail("target branch missing")
    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "terminal-ship-run",
                "dry_run": True,
                "steps": ["terminal-pr-prepare", "push-head", "gate-watch", "stabilize-within-budget"],
                "neverAutoMergesMain": True,
            }
        )
    if is_local_host_mode(root):
        cmd_terminal_pr_prepare(root, [])
        gate_ec, gate = run_check_gate(root, None)
        state = load_state(root)
        state["terminalShip"] = {
            "status": "gate-green" if gate_ec == 0 and gate.get("verdict") == "green" else "local-evidence",
            "mode": "local-evidence",
            "updatedAt": utc_now(),
        }
        save_state(root, state)
        payload = terminal_local_gate_payload(root, gate_ec, gate, action="terminal-ship-run")
        append_log(root, {"event": "terminal-ship-local", "gateVerdict": gate.get("verdict")})
        emit(payload, 0 if payload["verdict"] == "pass" else 10)
    cmd_terminal_pr_prepare(root, [])
    state = load_state(root)
    top = git_top(root)
    host_remote = remote_name(load_workflow_config(root))
    push = git_run(["push", "-u", host_remote, target], cwd=top, check=False)
    if push.returncode != 0:
        fail(
            push.stderr.strip() or "git push failed",
            exit_code=push.returncode,
            halt="blocked",
            cause="terminal-ship:push-failed",
        )
    terminal = state.get("terminalPr") or {}
    pr = terminal.get("number")
    if not pr:
        fail("terminal PR missing after prepare")
    pr_str = str(pr)
    max_attempts = remediation_max_attempts(root)
    terminal_attempts = int((state.get("remediationAttempts") or {}).get("terminal", 0))
    gate_ec, gate = run_check_gate(root, pr_str)
    ready = gate_ec == 0 and gate.get("verdict") == "green"
    state["terminalShip"] = {
        "status": "gate-green" if ready else "watching",
        "pr": pr,
        "attempts": terminal_attempts,
        "updatedAt": utc_now(),
    }
    save_state(root, state)
    if ready:
        append_log(root, {"event": "terminal-ship-gate-green", "pr": pr})
        emit(
            {
                "verdict": "pass",
                "action": "terminal-ship-run",
                "gate": gate,
                "terminalGate": "ready to merge — your call",
                "neverAutoMergesMain": True,
                "note": "Human merge gate preserved (R23)",
            }
        )
    if terminal_attempts >= max_attempts:
        fail(
            "terminal stabilization budget exhausted",
            exit_code=20,
            halt="blocked",
            cause="terminal-ship:remediation-exhausted",
            attempts=terminal_attempts,
            maxAttempts=max_attempts,
            recommendedCommand="/sw-stabilize",
        )
    state.setdefault("remediationAttempts", {})["terminal"] = terminal_attempts + 1
    save_state(root, state)
    emit(
        {
            "verdict": "wait",
            "action": "terminal-ship-run",
            "gate": gate,
            "gateExitCode": gate_ec,
            "attempt": terminal_attempts + 1,
            "maxAttempts": max_attempts,
            "recommendedCommand": "/sw-stabilize",
            "neverAutoMergesMain": True,
            "note": "Gate not green — stabilize within budget then re-run terminal ship",
        },
        exit_code=10,
    )




def is_local_host_mode(root: Path) -> bool:
    return resolve_provider(root).get("provider") == "none"


def write_local_merge_gate(root: Path, head: str, gate: dict[str, Any]) -> Path:
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        json.dump(gate, tf)
        gate_path = tf.name
    proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "local_merge_gate.py"),
            "--root",
            str(root),
            "write",
            "--head",
            head,
            "--gate-json",
            gate_path,
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    Path(gate_path).unlink(missing_ok=True)
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout)
        except json.JSONDecodeError:
            err = {"error": proc.stderr.strip() or proc.stdout.strip()}
        fail(err.get("error", "local merge gate write failed"), exit_code=proc.returncode)
    out = json.loads(proc.stdout)
    return Path(out.get("path", ""))


def terminal_local_gate_payload(root: Path, gate_ec: int, gate: dict[str, Any], *, action: str) -> dict[str, Any]:
    head = str(gate.get("head") or resolve_ref(git_top(root), "HEAD") or "")
    artifact_path = write_local_merge_gate(root, head, gate) if head else None
    ready = gate_ec == 0 and gate.get("verdict") == "green"
    payload: dict[str, Any] = {
        "verdict": "pass" if ready else "wait",
        "action": action,
        "source": "local-evidence",
        "gate": gate,
        "gateExitCode": gate_ec,
        "neverAutoMergesMain": True,
        "humanMergeRequired": True,
        "localMergeGateHalt": True,
        "note": "Local mode — final trunk merge halts for explicit human action (R11)",
    }
    if artifact_path:
        payload["localMergeGatePath"] = str(artifact_path)
    if ready:
        payload["terminalGate"] = "ready to merge — your call"
    else:
        payload["reason"] = gate.get("reason") or "gate not green"
    return payload

def default_base_branch(root: Path) -> str:
    cfg = load_workflow_config(root)
    base = cfg.get("defaultBaseBranch")
    if isinstance(base, str) and base:
        return base
    script = SCRIPT_DIR / "resolve_base_branch.py"
    if script.is_file():
        proc = subprocess.run(
            [sys.executable, str(script), "trunk-name"],
            cwd=str(root),
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    cfg = load_workflow_config(root)
    return str(cfg.get("defaultBaseBranch") or "main")


def git_top(root: Path) -> Path:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail("not a git repository")
    return Path(proc.stdout.strip())


def git_run(args: list[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git"] + args, cwd=str(cwd), text=True, capture_output=True, check=check)


def resolve_ref(cwd: Path, ref: str) -> str | None:
    proc = git_run(["rev-parse", ref], cwd=cwd, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def is_ancestor(ancestor: str, descendant: str, cwd: Path) -> bool:
    proc = git_run(["merge-base", "--is-ancestor", ancestor, descendant], cwd=cwd, check=False)
    return proc.returncode == 0


def run_tasks_currency_gate(root: Path, state: dict[str, Any]) -> None:
    """Hard-block terminal gate when task-list currency diverges (R7)."""
    from wave_deliver_loop import load_plan, tasks_currency_ok

    plan: dict[str, Any] = {}
    plan_path = root / ".cursor" / "sw-deliver-plan.json"
    if plan_path.is_file():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            plan = {}
    ok, cause = tasks_currency_ok(root, state, plan)
    if not ok:
        fail(
            "task-list currency divergence",
            exit_code=1,
            halt="blocked",
            cause=cause or "tasks-currency-divergence",
        )


def run_docs_currency_gate(root: Path) -> None:
    """Hard-block terminal gate on living-doc drift for the current run (R50)."""
    if os.environ.get("SW_SKIP_DOCS_CURRENCY") == "1":
        return
    script = SCRIPT_DIR / "docs-currency-gate.py"
    proc = subprocess.run(
        ["bash", str(script), "--state-root", str(root)],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout)
        except json.JSONDecodeError:
            err = {"error": proc.stderr.strip() or proc.stdout.strip() or "docs-currency gate failed"}
        fail(
            err.get("error", "living-doc currency drift"),
            exit_code=proc.returncode or 1,
            halt="blocked",
            cause="docs-currency:drift",
            **{k: v for k, v in err.items() if k != "error"},
        )


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.py"
    cmd = ["bash", str(script)]
    if pr:
        cmd.append(pr)
    proc = subprocess.run(cmd, cwd=str(root), text=True, capture_output=True)
    try:
        gate = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        gate = {"verdict": "blocked", "reason": proc.stderr.strip() or "invalid gate output"}
    return proc.returncode, gate


def append_log(root: Path, entry: dict[str, Any]) -> None:
    log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)
    os.chmod(log_path, 0o600)


def all_phases_green(state: dict[str, Any]) -> bool:
    phases = state.get("phases") or {}
    if not phases:
        return False
    return all(phase_complete(meta.get("status")) for meta in phases.values())


def host_pr_list(root: Path, *, head: str, base: str, state: str = "open") -> list[dict[str, Any]]:
    out = host_verb(root, "pr-list", head=head, base=base, state=state)
    if out.get("verdict") != "ok":
        fail(out.get("reason", "host pr-list failed"), exit_code=out.get("_exitCode", 30))
    data = out.get("data")
    return data if isinstance(data, list) else []


def host_pr_create(root: Path, *, title: str, body: str, head: str, base: str) -> dict[str, Any]:
    from host_lib import phase_mode_active
    from wave_phase_pr import create_or_reuse_phase_pr, enforce_phase_pr_base

    resolved = enforce_phase_pr_base(root, base)
    if resolved.get("verdict") != "ok":
        fail(resolved.get("error", "phase-pr-base"), exit_code=20, **{k: v for k, v in resolved.items() if k != "verdict"})
    base = str(resolved.get("base") or base)

    if phase_mode_active():
        phase_slug = os.environ.get("SW_PHASE_SLUG", "").strip()
        if not phase_slug:
            fail("SW_PHASE_SLUG required for phase-mode pr-create", exit_code=20)
        out = create_or_reuse_phase_pr(
            root,
            phase_slug=phase_slug,
            head=head,
            title=title,
            body=body,
        )
        if out.get("verdict") != "ok":
            fail(out.get("error") or out.get("reason", "phase-pr-create-failed"), exit_code=20, **out)
        data = out.get("pr") if isinstance(out.get("pr"), dict) else {}
        return data

    out = host_verb(root, "pr-create", title=title, body=body, head=head, base=base)
    if out.get("verdict") != "ok":
        fail(out.get("reason", "host pr-create failed"), exit_code=out.get("_exitCode", 30))
    data = out.get("data")
    return data if isinstance(data, dict) else {}


def record_merge_for_ack(root: Path) -> dict[str, Any]:
    state = load_state(root)
    cadence = phase_ack_cadence(root)
    merges = int(state.get("mergesSinceAck") or 0) + 1
    state["mergesSinceAck"] = merges
    ack_pending = False
    if cadence > 0 and merges >= cadence:
        state["ackPending"] = True
        state["ackPendingAt"] = utc_now()
        ack_pending = True
    save_state(root, state)
    if ack_pending:
        append_log(root, {"event": "ack-pending", "cadence": cadence, "mergesSinceAck": merges})
    return {"mergesSinceAck": merges, "cadence": cadence, "ackPending": ack_pending}


def cmd_resume_reconcile(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    state = load_state(root)
    if not state:
        fail("run state missing")
    target = (state.get("target") or {}).get("branch")
    if not target:
        fail("target branch missing in run-state")
    top = git_top(root)
    host_remote = remote_name(load_workflow_config(root))
    if not has_flag(args, "--no-fetch"):
        git_run(["fetch", host_remote, target], cwd=top, check=False)

    remote_ref_name = remote_ref(host_remote, target)
    remote_tip = resolve_ref(top, remote_ref_name)
    local_tip = resolve_ref(top, target)
    ground_tip = remote_tip or local_tip
    if not ground_tip:
        fail(f"cannot resolve tip for {target!r} (fetch {host_remote}/{target} first)")

    phases = state.get("phases") or {}
    promoted: list[str] = []
    demoted: list[str] = []
    skipped: list[str] = []

    for pid, meta in phases.items():
        slug = meta.get("slug", pid)
        branch = meta.get("branch")
        status = meta.get("status")
        if not branch:
            if status == "green-merged":
                skipped.append(slug)
            continue
        phase_sha = resolve_ref(top, branch)
        if not phase_sha:
            if status == "green-merged":
                if not dry_run:
                    meta["status"] = "pending"
                    meta.pop("mergeCommit", None)
                    meta["updatedAt"] = utc_now()
                    meta["cause"] = "resume:missing-phase-branch"
                demoted.append(slug)
            continue
        merged_on_remote = is_ancestor(phase_sha, ground_tip, top)
        if status == "green-merged":
            if merged_on_remote:
                skipped.append(slug)
            else:
                if not dry_run:
                    meta["status"] = "pending"
                    meta.pop("mergeCommit", None)
                    meta["updatedAt"] = utc_now()
                    meta["cause"] = "resume:unpushed-local-merge"
                demoted.append(slug)
            continue
        if merged_on_remote:
            if not dry_run:
                meta["status"] = "green-merged"
                meta["updatedAt"] = utc_now()
                meta["reconciledFrom"] = remote_ref if remote_tip else target
            promoted.append(slug)

    if not dry_run:
        state["phases"] = phases
        state["remoteTargetTip"] = ground_tip
        state["reconciledAt"] = utc_now()
        save_state(root, state)
        append_log(
            root,
            {
                "event": "resume-reconcile",
                "promoted": promoted,
                "demoted": demoted,
                "groundTip": ground_tip,
            },
        )

    emit(
        {
            "verdict": "pass",
            "action": "resume-reconcile",
            "dry_run": dry_run,
            "target": target,
            "groundTip": ground_tip,
            "promoted": promoted,
            "demoted": demoted,
            "skippedGreenMerged": skipped,
            "note": "Remote pushed tip is ground truth (R29/R50)",
        }
    )


def terminal_pr_body(state: dict[str, Any]) -> str:
    lines = ["## Phase PRs", ""]
    for record in state.get("mergedPhases") or []:
        slug = record.get("phaseSlug", "?")
        pr = record.get("pr")
        if pr:
            lines.append(f"- {slug}: #{pr}")
        else:
            lines.append(f"- {slug}")
    lines.append("")
    lines.append("Delivered via `/sw-deliver` phase-mode. Human merge gate — do not auto-merge.")
    return "\n".join(lines)


def cmd_terminal_pr_prepare(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run") or os.environ.get("SW_DELIVER_DRY_RUN") == "1"
    state = load_state(root)
    target = (state.get("target") or {}).get("branch", "")
    slug = (state.get("target") or {}).get("slug", target.split("/")[-1] if target else "feature")
    commit_type = (state.get("target") or {}).get("type", "feat")
    base = default_base_branch(root)

    if state.get("terminalRejected"):
        fail(
            "terminal PR was rejected; resume must not re-present (R46)",
            exit_code=20,
            halt="rejected",
            scope=state.get("terminalRejectScope"),
        )
    if not all_phases_green(state):
        fail("terminal PR only when all phases are green-merged (R22)", exit_code=20)

    if is_local_host_mode(root):
        prd_number = state.get("prd_number")
        title = parse_kv(args, "--title") or commitlint_safe_title(commit_type, slug, prd_number)
        if dry_run:
            emit(
                {
                    "verdict": "pass",
                    "action": "terminal-local-prepare",
                    "dry_run": True,
                    "head": target,
                    "base": base,
                    "source": "local-evidence",
                    "neverAutoMergesMain": True,
                }
            )
        if not dry_run:
            append_proc = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "wave_living_docs.py"),
                    str(root),
                    "append-terminal",
                    "--commit",
                ],
                cwd=str(root),
                text=True,
                capture_output=True,
            )
            if append_proc.returncode not in (0, 10):
                try:
                    err = json.loads(append_proc.stdout)
                except json.JSONDecodeError:
                    err = {"error": append_proc.stderr or append_proc.stdout}
                fail(err.get("error", "living-docs append-terminal failed"), exit_code=append_proc.returncode)
            run_tasks_currency_gate(root, state)
        run_docs_currency_gate(root)
        state = load_state(root)
        state["terminalLocalGate"] = {
            "mode": "local-evidence",
            "headBranch": target,
            "base": base,
            "title": title,
            "preparedAt": utc_now(),
        }
        state.pop("terminalPr", None)
        save_state(root, state)
        append_log(root, {"event": "terminal-local-prepare", "target": target, "source": "local-evidence"})
        emit(
            {
                "verdict": "pass",
                "action": "terminal-local-prepare",
                "terminalLocalGate": state["terminalLocalGate"],
                "neverAutoMergesMain": True,
                "humanMergeRequired": True,
                "note": "No-remote mode — terminal gate uses local-evidence artifact (R10/R11)",
            }
        )

    if not dry_run:
        append_proc = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "wave_living_docs.py"),
                str(root),
                "append-terminal",
                "--commit",
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if append_proc.returncode not in (0, 10):
            try:
                err = json.loads(append_proc.stdout)
            except json.JSONDecodeError:
                err = {"error": append_proc.stderr or append_proc.stdout}
            fail(err.get("error", "living-docs append-terminal failed"), exit_code=append_proc.returncode)
        run_tasks_currency_gate(root, state)
        run_docs_currency_gate(root)

    prd_number = state.get("prd_number")
    title = parse_kv(args, "--title") or commitlint_safe_title(commit_type, slug, prd_number)
    body = terminal_pr_body(state)

    if dry_run:
        emit(
            {
                "verdict": "pass",
                "action": "terminal-pr-prepare",
                "dry_run": True,
                "head": target,
                "base": base,
                "title": title,
                "wouldCreate": not bool(state.get("terminalPr")),
            }
        )

    top = git_top(root)
    items = host_pr_list(root, head=target, base=base, state="open")
    pr_info: dict[str, Any] | None = None
    if items:
        first = items[0]
        pr_info = {
            "number": first.get("number"),
            "url": first.get("url"),
            "head": first.get("headRefOid"),
        }

    if not pr_info:
        created = host_pr_create(root, title=title, body=body, head=target, base=base)
        pr_info = {
            "number": created.get("number"),
            "url": created.get("url"),
            "head": created.get("headRefOid"),
        }

    state = load_state(root)
    state["terminalPr"] = {
        **pr_info,
        "base": base,
        "headBranch": target,
        "preparedAt": utc_now(),
    }
    save_state(root, state)
    append_log(root, {"event": "terminal-pr-prepare", "pr": pr_info.get("number"), "url": pr_info.get("url")})
    emit(
        {
            "verdict": "pass",
            "action": "terminal-pr-prepare",
            "terminalPr": state["terminalPr"],
            "note": "Single <type>/<slug> → main PR; halt at human gate (R23)",
        }
    )


def cmd_terminal_pr_gate(root: Path, args: list[str]) -> None:
    state = load_state(root)
    if state.get("terminalRejected"):
        fail("terminal PR rejected; gate not applicable (R46)", exit_code=20)
    if is_local_host_mode(root) or state.get("terminalLocalGate"):
        run_docs_currency_gate(root)
        gate_ec, gate = run_check_gate(root, None)
        payload = terminal_local_gate_payload(root, gate_ec, gate, action="terminal-local-gate")
        ready = payload["verdict"] == "pass"
        emit(payload, 0 if ready else 10)
    terminal = state.get("terminalPr") or {}
    pr = parse_kv(args, "--pr") or (str(terminal.get("number")) if terminal.get("number") else None)
    if not pr:
        fail("terminal PR not prepared; run terminal pr prepare first")
    run_docs_currency_gate(root)
    gate_ec, gate = run_check_gate(root, pr)
    ready = gate_ec == 0 and gate.get("verdict") == "green"
    payload = {
        "verdict": "pass" if ready else "wait",
        "action": "terminal-pr-gate",
        "pr": int(pr) if str(pr).isdigit() else pr,
        "gate": gate,
        "gateExitCode": gate_ec,
        "terminalGate": "ready to merge — your call" if ready else None,
        "neverAutoMergesMain": True,
        "note": "Authoritative whole-feature verdict from check-gate.py (R23/R24)",
    }
    if not ready:
        payload["reason"] = gate.get("reason") or "gate not green"
    emit(payload, 0 if ready else 10)


def cmd_terminal_pr_status(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    emit(
        {
            "verdict": "pass",
            "action": "terminal-pr-status",
            "terminalPr": state.get("terminalPr"),
            "terminalRejected": bool(state.get("terminalRejected")),
            "allPhasesGreen": all_phases_green(state),
        }
    )


def cmd_ack_status(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    cadence = phase_ack_cadence(root)
    emit(
        {
            "verdict": "pass",
            "action": "ack-status",
            "cadence": cadence,
            "mergesSinceAck": int(state.get("mergesSinceAck") or 0),
            "ackPending": bool(state.get("ackPending")),
            "ackPendingAt": state.get("ackPendingAt"),
        }
    )


def cmd_ack_check(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    cadence = phase_ack_cadence(root)
    if cadence <= 0:
        emit({"verdict": "pass", "action": "ack-check", "cadence": 0, "ackRequired": False})
    if state.get("ackPending"):
        emit(
            {
                "verdict": "halt",
                "action": "ack-check",
                "ackRequired": True,
                "cadence": cadence,
                "mergesSinceAck": state.get("mergesSinceAck"),
                "halt": "need-ack",
                "note": f"Human ack required after {cadence} phase merge(s) (R56)",
            },
            exit_code=11,
        )
    emit(
        {
            "verdict": "pass",
            "action": "ack-check",
            "ackRequired": False,
            "cadence": cadence,
            "mergesSinceAck": state.get("mergesSinceAck", 0),
        }
    )


def cmd_ack_complete(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    state["ackPending"] = False
    state.pop("ackPendingAt", None)
    state["mergesSinceAck"] = 0
    state["lastAckAt"] = utc_now()
    save_state(root, state)
    append_log(root, {"event": "ack-complete"})
    emit({"verdict": "pass", "action": "ack-complete", "note": "Resume phase dispatch"})


def main() -> None:
    if len(sys.argv) < 3:
        fail("usage: wave_terminal.py <root> <domain> <subcommand> [args...]")
    root = Path(sys.argv[1])
    domain = sys.argv[2]
    args = sys.argv[3:]

    if domain == "resume":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "reconcile":
            cmd_resume_reconcile(root, rest)
        else:
            fail("resume subcommand required: reconcile")
    elif domain == "terminal":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "autonomy":
            cmd_terminal_autonomy(root, rest)
        elif sub == "retro":
            retro_sub = rest[0] if rest else ""
            retro_rest = rest[1:]
            if retro_sub == "run":
                cmd_terminal_retro_run(root, retro_rest)
            else:
                fail("terminal retro subcommand required: run")
        elif sub == "checkpoint":
            cmd_terminal_checkpoint(root, rest)
        elif sub == "ship":
            ship_sub = rest[0] if rest else ""
            ship_rest = rest[1:]
            if ship_sub == "run":
                cmd_terminal_ship_run(root, ship_rest)
            else:
                fail("terminal ship subcommand required: run")
        elif sub == "pr":
            pr_sub = rest[0] if rest else ""
            pr_rest = rest[1:]
            if pr_sub == "prepare":
                cmd_terminal_pr_prepare(root, pr_rest)
            elif pr_sub == "gate":
                cmd_terminal_pr_gate(root, pr_rest)
            elif pr_sub == "status":
                cmd_terminal_pr_status(root, pr_rest)
            else:
                fail("terminal pr subcommand required: prepare|gate|status")
        else:
            fail("terminal subcommand required: pr")
    elif domain == "ack":
        sub = args[0] if args else ""
        rest = args[1:]
        if sub == "status":
            cmd_ack_status(root, rest)
        elif sub == "check":
            cmd_ack_check(root, rest)
        elif sub == "complete":
            cmd_ack_complete(root, rest)
        elif sub == "record-merge":
            emit({"verdict": "pass", "action": "ack-record-merge", **record_merge_for_ack(root)})
        else:
            fail("ack subcommand required: status|check|complete|record-merge")
    else:
        fail(f"unknown domain: {domain}")


if __name__ == "__main__":
    main()
