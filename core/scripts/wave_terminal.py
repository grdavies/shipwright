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


def state_path(root: Path) -> Path:
    return root / ".cursor" / "sw-deliver-state.json"


def load_state(root: Path) -> dict[str, Any]:
    return read_json(state_path(root))


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["updatedAt"] = utc_now()
    write_json(state_path(root), state)


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


def default_base_branch(root: Path) -> str:
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


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.sh"
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
    for meta in phases.values():
        if meta.get("status") != "green-merged":
            return False
    return True


def gh_json(args: list[str], cwd: Path) -> Any:
    proc = subprocess.run(
        ["gh", *args],
        cwd=str(cwd),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "gh command failed", exit_code=proc.returncode)
    return json.loads(proc.stdout or "null")


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
    if not has_flag(args, "--no-fetch"):
        git_run(["fetch", "origin", target], cwd=top, check=False)

    remote_ref = f"origin/{target}"
    remote_tip = resolve_ref(top, remote_ref)
    local_tip = resolve_ref(top, target)
    ground_tip = remote_tip or local_tip
    if not ground_tip:
        fail(f"cannot resolve tip for {target!r} (fetch origin/{target} first)")

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

    title = parse_kv(args, "--title") or f"{commit_type}({slug}): deliver wave"
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
    existing = subprocess.run(
        ["gh", "pr", "list", "--head", target, "--base", base, "--json", "number,url,headRefOid"],
        cwd=str(top),
        text=True,
        capture_output=True,
    )
    pr_info: dict[str, Any] | None = None
    if existing.returncode == 0 and existing.stdout.strip():
        items = json.loads(existing.stdout)
        if items:
            pr_info = {
                "number": items[0]["number"],
                "url": items[0]["url"],
                "head": items[0].get("headRefOid"),
            }

    if not pr_info:
        create = subprocess.run(
            [
                "gh",
                "pr",
                "create",
                "--base",
                base,
                "--head",
                target,
                "--title",
                title,
                "--body",
                body,
            ],
            cwd=str(top),
            text=True,
            capture_output=True,
        )
        if create.returncode != 0:
            fail(create.stderr.strip() or create.stdout.strip() or "gh pr create failed")
        url = create.stdout.strip()
        number_proc = subprocess.run(
            ["gh", "pr", "view", url, "--json", "number,url,headRefOid"],
            cwd=str(top),
            text=True,
            capture_output=True,
        )
        if number_proc.returncode == 0:
            pr_info = json.loads(number_proc.stdout)
        else:
            pr_info = {"url": url}

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
    terminal = state.get("terminalPr") or {}
    pr = parse_kv(args, "--pr") or (str(terminal.get("number")) if terminal.get("number") else None)
    if not pr:
        fail("terminal PR not prepared; run terminal pr prepare first")
    gate_ec, gate = run_check_gate(root, pr)
    ready = gate_ec == 0 and gate.get("verdict") == "green"
    payload: dict[str, Any] = {
        "verdict": "pass" if ready else "wait",
        "action": "terminal-pr-gate",
        "pr": int(pr) if str(pr).isdigit() else pr,
        "gate": gate,
        "gateExitCode": gate_ec,
        "terminalGate": "ready to merge — your call" if ready else None,
        "note": "Authoritative whole-feature verdict from check-gate.sh (R23/R24)",
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
        if sub == "pr":
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
