#!/usr/bin/env python3
"""Terminal PR gate, idempotent resume, and phase ack cadence for /sw-deliver (R22–R24, R29–R30, R43, R56)."""
from __future__ import annotations

import contextvars
import json
import os
import re
import subprocess

from _sw import interpreter
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent

if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from host_invoke import host_verb
from wave_errors import fail_from_payload
from host_lib import load_workflow_config, remote_name, remote_ref, resolve_provider
from host import probe_remote_ref_exists
from host_ratelimit import HostProbeInconclusive, HostRateLimited
from wave_state import phase_complete
import loop_health_lib
import planning_gap_capture as pgc


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class TerminalOutcome:
    """Library result for terminal helpers — no process exit (PRD 069 R1)."""

    payload: dict[str, Any]
    exit_code: int = 0


class TerminalExit(Exception):
    """Raised from emit/fail when terminal_library_mode is active."""

    def __init__(self, outcome: TerminalOutcome) -> None:
        self.outcome = outcome
        super().__init__(outcome.payload.get("error") or outcome.payload.get("verdict"))


_terminal_library_mode: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_terminal_library_mode", default=False
)


@contextmanager
def terminal_library_mode():
    """Route emit/fail to TerminalOutcome instead of sys.exit."""
    token = _terminal_library_mode.set(True)
    try:
        yield
    finally:
        _terminal_library_mode.reset(token)


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    if _terminal_library_mode.get():
        raise TerminalExit(TerminalOutcome(obj, exit_code))
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: Any, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": str(error), **extra}, exit_code)


def emit_outcome(outcome: TerminalOutcome) -> None:
    emit(outcome.payload, outcome.exit_code)


_H1_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$")
_PRD_HEADING_PREFIX_RE = re.compile(r"^PRD\s+\d+[A-Za-z]?\s*[—\-:]\s*", re.I)


def _first_markdown_h1(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    i = 0
    if lines and lines[0].strip() == "---":
        i = 1
        while i < len(lines) and lines[i].strip() != "---":
            i += 1
        i += 1
    for line in lines[i:]:
        match = _H1_HEADING_RE.match(line)
        if match:
            return match.group(1).strip()
    return None


def prd_feature_title(root: Path, prd_number: str) -> str | None:
    """Resolve the PRD's human-readable feature name from its H1 heading (R20).

    Strips a leading ``PRD <n>[<letter>] — `` (or ``-``/``:``) prefix so the
    title names the landed feature rather than restating the PRD number.
    """
    padded = str(prd_number).zfill(3)
    prds_dir = root / "docs" / "prds"
    if not prds_dir.is_dir():
        return None
    for unit_dir in sorted(prds_dir.glob(f"{padded}-*")):
        if not unit_dir.is_dir():
            continue
        for md in sorted(unit_dir.glob(f"{padded}-prd-*.md")):
            heading = _first_markdown_h1(md)
            if heading:
                stripped = _PRD_HEADING_PREFIX_RE.sub("", heading).strip()
                return stripped or heading
    return None


def slug_feature_title(slug: str) -> str:
    """Title-case a task-list/target slug into a feature name fallback (R20)."""
    words = [w for w in re.split(r"[-_]+", slug.strip()) if w]
    if not words:
        return "deliver wave"
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


def resolve_feature_title(root: Path, *, prd_number: str | None, slug: str) -> str:
    """PRD title, falling back to the task-list/target slug (R20)."""
    if prd_number:
        title = prd_feature_title(root, prd_number)
        if title:
            return title
    return slug_feature_title(slug)


def commit_description(feature_title: str, *, prefix_len: int, max_header: int = 100) -> str:
    """Lowercase, length-budgeted commit description naming the feature (R20).

    Fully lowercased (not just the leading letter) so the description never
    trips commitlint's ``subject-case`` rule (which forbids start-case) and
    so the release-please changelog line it feeds reads like a normal
    conventional-commit subject.
    """
    desc = feature_title.strip().lower()
    if not desc:
        return "deliver wave"
    budget = max(10, max_header - prefix_len)
    if len(desc) > budget:
        truncated = desc[:budget].rstrip()
        if " " in truncated:
            truncated = truncated.rsplit(" ", 1)[0]
        desc = truncated or desc[:budget]
    return desc


def commitlint_safe_title(
    commit_type: str,
    slug: str,
    prd_number: str | None = None,
    *,
    root: Path | None = None,
) -> str:
    """Conventional-commit title naming the landed feature (R20; R43 lowercase prd scope).

    Derives the description from the PRD title (its H1 heading) when a
    ``root`` is supplied and a PRD file resolves; otherwise falls back to a
    title-cased rendering of ``slug``. Replaces the previous fixed
    ``deliver wave`` text so terminal PR titles and release-please changelog
    entries (which release-please derives from this same commit message)
    name what actually landed.
    """
    feature_title = resolve_feature_title(root, prd_number=prd_number, slug=slug) if root else slug_feature_title(slug)
    if prd_number:
        num = str(prd_number).lstrip("0") or "0"
        scope = f"prd-{num}".lower()
        prefix = f"{commit_type}({scope}): "
        return f"{prefix}{commit_description(feature_title, prefix_len=len(prefix))}"
    safe_slug = slug.lower().replace("_", "-")
    prefix = f"{commit_type}({safe_slug}): "
    return f"{prefix}{commit_description(feature_title, prefix_len=len(prefix))}"


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


def terminal_gap_capture_config(root: Path) -> dict[str, Any]:
    """`deliver.terminal.gapCapture` settings (R19), defaulting to enabled."""
    deliver = load_workflow_config(root).get("deliver") or {}
    terminal = deliver.get("terminal") or {}
    cfg = terminal.get("gapCapture") or {}
    max_captures = cfg.get("maxCapturesPerRun")
    if not isinstance(max_captures, int) or max_captures < 0:
        max_captures = pgc.DEFAULT_MAX_TERMINAL_CAPTURES
    return {
        "enabled": cfg.get("enabled") is not False,
        "maxCapturesPerRun": max_captures,
    }


_FRICTION_LOG_EVENT_ACK_PENDING = "ack-pending"
_FRICTION_LOG_EVENT_RESUME_RECONCILE = "resume-reconcile"


def scan_run_log_friction(root: Path) -> dict[str, int]:
    """Tally recurring friction signals from the deliver run log (R19).

    Counts repeated phase-ack-cadence halts and resume-reconcile demotions
    (unpushed local phase merges) — both are evidence of unaddressed
    planning-store/process pain rather than one-off noise.
    """
    counts = {"ackPending": 0, "resumeDemotions": 0}
    log_path = root / ".cursor" / "sw-deliver-runs" / "run.log"
    if not log_path.is_file():
        return counts
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return counts
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        event = entry.get("event")
        if event == _FRICTION_LOG_EVENT_ACK_PENDING:
            counts["ackPending"] += 1
        elif event == _FRICTION_LOG_EVENT_RESUME_RECONCILE:
            demoted = entry.get("demoted")
            if isinstance(demoted, list):
                counts["resumeDemotions"] += len(demoted)
    return counts


def derive_terminal_pain_items(root: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate run-log friction + loop-health metrics into candidate gap-capture
    pain items for the terminal auto-capture engine (R19).

    Each item carries a stable ``signalId`` (idempotent across repeated
    terminal runs), a human ``title`` (the candidate gap title),
    ``category``/``severity``/``recurrence`` for
    :func:`planning_gap_capture.classify_pain_item`, and ``source`` for
    provenance.
    """
    items: list[dict[str, Any]] = []
    friction = scan_run_log_friction(root)
    if friction["ackPending"] >= 2:
        items.append(
            {
                "signalId": "terminal-friction:ack-pending",
                "title": "Deliver phase-ack cadence repeatedly pending human review",
                "category": "ack-pending",
                "severity": "medium",
                "recurrence": friction["ackPending"],
                "source": "run-log",
            }
        )
    if friction["resumeDemotions"] >= 1:
        items.append(
            {
                "signalId": "terminal-friction:resume-demotion",
                "title": "Deliver resume repeatedly demoted unpushed phase merges",
                "category": "resume-reconcile",
                "severity": "high" if friction["resumeDemotions"] >= 2 else "medium",
                "recurrence": friction["resumeDemotions"],
                "source": "run-log",
            }
        )
    record = loop_health_lib.build_record(root)
    metrics = record.get("metrics") if isinstance(record.get("metrics"), dict) else {}
    rework = metrics.get("reworkDefect") if isinstance(metrics.get("reworkDefect"), dict) else {}
    reopened = int(rework.get("reopenedPhases") or 0)
    reverts = int(rework.get("postMergeReverts") or 0)
    if reopened >= 1:
        items.append(
            {
                "signalId": "terminal-friction:reopened-phases",
                "title": "Deliver run reopened previously green phases",
                "category": "reopened-phases",
                "severity": "high" if reopened >= 2 else "medium",
                "recurrence": reopened,
                "source": "loop-health",
            }
        )
    if reverts >= 1:
        items.append(
            {
                "signalId": "terminal-friction:post-merge-revert",
                "title": "Deliver run required a post-merge revert",
                "category": "post-merge-revert",
                "severity": "critical",
                "recurrence": reverts,
                "source": "loop-health",
            }
        )
    review = metrics.get("reviewEffort") if isinstance(metrics.get("reviewEffort"), dict) else {}
    stabilize = int(review.get("stabilizeReentries") or 0)
    if stabilize >= 2:
        items.append(
            {
                "signalId": "terminal-friction:stabilize-reentry",
                "title": "Deliver run re-entered stabilization repeatedly",
                "category": "stabilize-reentry",
                "severity": "high" if stabilize >= 3 else "medium",
                "recurrence": stabilize,
                "source": "loop-health",
            }
        )
    return items


def run_terminal_gap_capture(
    root: Path,
    *,
    verdict: str,
    dry_run: bool = False,
    confirmed_signal_ids: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Terminal auto-capture engine entry point (R19, gap-032).

    Diagnostic and best-effort by design: scans run-log + loop-health for
    unaddressed planning-store pain and hands the candidates to
    :func:`planning_gap_capture.terminal_capture`, which suppresses on
    fail/aborted verdicts, dedups against open gap titles, applies the
    substantial-vs-noise heuristic, and caps captures per run.
    """
    cfg = terminal_gap_capture_config(root)
    if not cfg["enabled"]:
        return {"skipped": True, "reason": "deliver.terminal.gapCapture.enabled is false"}
    state = load_state(root)
    items = derive_terminal_pain_items(root, state)
    result = pgc.terminal_capture(
        root,
        verdict=verdict,
        pain_items=items,
        max_captures=cfg["maxCapturesPerRun"],
        dry_run=dry_run,
        confirmed_signal_ids=confirmed_signal_ids,
    )
    if not dry_run:
        append_log(
            root,
            {
                "event": "terminal-gap-capture",
                "verdict": verdict,
                "captured": len(result.get("captured") or []),
                "pending": len(result.get("pending") or []),
                "skippedNoise": len(result.get("skippedNoise") or []),
                "skippedDuplicate": len(result.get("skippedDuplicate") or []),
            },
        )
    return result


def parse_repeated_kv(args: list[str], flag: str) -> set[str]:
    """Collect every value passed for a repeatable ``--flag value`` pair."""
    out: set[str] = set()
    i = 0
    while i < len(args):
        if args[i] == flag and i + 1 < len(args):
            out.add(args[i + 1])
            i += 2
        else:
            i += 1
    return out


def terminal_gap_capture_best_effort(root: Path, *, verdict: str) -> dict[str, Any] | None:
    """Fire-and-forget wrapper for the terminal-ready call sites (R19).

    Diagnostic and non-gating by design (matches loop-health's
    ``diagnosticOnly``/``gating: false`` posture): a failure here must never
    block the actual terminal ship gate, so any exception is swallowed and
    logged rather than propagated.
    """
    try:
        return run_terminal_gap_capture(root, verdict=verdict)
    except Exception as exc:  # noqa: BLE001 — best-effort, never blocks terminal ship (R19)
        try:
            append_log(root, {"event": "terminal-gap-capture-error", "error": str(exc)})
        except Exception:  # noqa: BLE001 — logging itself must never raise here
            pass
        return None


def cmd_terminal_gap_capture_run(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    verdict = parse_kv(args, "--verdict") or str(load_state(root).get("verdict") or "running")
    confirm_ids = parse_repeated_kv(args, "--confirm")
    result = run_terminal_gap_capture(
        root,
        verdict=verdict,
        dry_run=dry_run,
        confirmed_signal_ids=confirm_ids or None,
    )
    emit({"verdict": "pass", "action": "terminal-gap-capture", **result})


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
            retro = run_terminal_retro(root, ["--force"])
            if retro.exit_code != 0:
                emit_outcome(retro)
            state = load_state(root)
        if needs_ship:
            ship = run_terminal_ship_run(root, ["--force"])
            if ship.exit_code != 0:
                emit_outcome(ship)
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
            "reportTerminal": "bash scripts/wave.py report terminal",
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
    """CLI wrapper — emit+exit after library helper (PRD 069 R1)."""
    emit_outcome(run_terminal_retro(root, args))


def _cmd_terminal_retro_run_body(root: Path, args: list[str]) -> None:
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
    """CLI wrapper — emit+exit after library helper (PRD 069 R1)."""
    emit_outcome(run_terminal_ship_run(root, args))


def _cmd_terminal_ship_run_body(root: Path, args: list[str], *, dry_run: bool) -> None:
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
        retro = run_terminal_retro(root, ["--force"])
        if retro.exit_code != 0:
            emit_outcome(retro)
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
        prep = run_terminal_pr_prepare(root, [], dry_run=False)
        if prep.exit_code != 0:
            emit_outcome(prep)
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
        if payload["verdict"] == "pass":
            terminal_gap_capture_best_effort(root, verdict="pass")
        emit(payload, 0 if payload["verdict"] == "pass" else 10)
    prep = run_terminal_pr_prepare(root, [], dry_run=False)
    if prep.exit_code != 0:
        emit_outcome(prep)
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
    gate_ec, gate = run_terminal_gate_watch(root, pr_str)
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
        terminal_gap_capture_best_effort(root, verdict="pass")
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


def clear_phase_env() -> dict[str, str]:
    """Clear SW_PHASE_* so terminal PR uses trunk base, not phase integration (PRD 067 R8)."""
    saved: dict[str, str] = {}
    for key in list(os.environ):
        if key.startswith("SW_PHASE_"):
            saved[key] = os.environ.pop(key)
    return saved


def restore_phase_env(saved: dict[str, str]) -> None:
    for key, value in saved.items():
        os.environ[key] = value

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


TERMINAL_PREPARE_RECOVERABLE_MARKERS = (
    "issue-store-unreachable",
    "planning-store-degraded",
    "prd-unit-not-found",
    "planning-store-put-failed",
)


def is_recoverable_planning_failure(payload: dict[str, Any] | None) -> bool:
    """Classify non-fatal planning_store / living-doc failures for terminal prepare (R5)."""
    if not isinstance(payload, dict):
        return False
    if payload.get("verdict") == "degraded":
        return True
    for key in ("notice", "error", "reason"):
        text = str(payload.get(key) or "")
        if any(marker in text for marker in TERMINAL_PREPARE_RECOVERABLE_MARKERS):
            return True
    append = payload.get("append")
    if isinstance(append, dict) and is_recoverable_planning_failure(append):
        return True
    return False


def _parse_subprocess_json(proc: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    try:
        payload = json.loads(proc.stdout)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass
    return {"error": proc.stderr.strip() or proc.stdout.strip() or "subprocess failed"}


def run_prepare_subprocess_recoverable(
    proc: subprocess.CompletedProcess[str],
    *,
    step: str,
) -> tuple[bool, dict[str, Any] | None, dict[str, Any] | None]:
    """Return (continue_ok, fatal_payload, degradation_notice)."""
    if proc.returncode == 0:
        payload = _parse_subprocess_json(proc)
        if is_recoverable_planning_failure(payload):
            return True, None, {"step": step, **payload}
        return True, None, None
    payload = _parse_subprocess_json(proc)
    if is_recoverable_planning_failure(payload):
        return True, None, {"step": step, **payload}
    return False, payload, None


def record_terminal_prepare_degradations(
    root: Path, state: dict[str, Any], notices: list[dict[str, Any]]
) -> None:
    if not notices:
        return
    state["terminalPrepareDegraded"] = {
        "notices": notices,
        "updatedAt": utc_now(),
    }
    save_state(root, state)


def run_living_docs_append_terminal(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    proc = subprocess.run(
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
    if proc.returncode in (0, 10):
        notices: list[dict[str, Any]] = []
        if proc.returncode == 0 and proc.stdout.strip():
            payload = _parse_subprocess_json(proc)
            if is_recoverable_planning_failure(payload):
                notices.append({"step": "append-terminal", **payload})
            append = payload.get("append")
            if isinstance(append, dict) and is_recoverable_planning_failure(append):
                notices.append({"step": "append-terminal", **append})
        return notices, None
    ok, fatal, notice = run_prepare_subprocess_recoverable(proc, step="append-terminal")
    if ok:
        return ([notice] if notice else []), None
    return [], fatal


def run_docs_currency_gate_for_prepare(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if os.environ.get("SW_SKIP_DOCS_CURRENCY") == "1":
        return [], None
    ensure_terminal_index_projection(root)
    script = SCRIPT_DIR / "docs-currency-gate.py"
    repo_root, state_root, state_path, plan_path = resolve_docs_currency_paths(root)
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repo_root),
            str(state_root),
            str(state_path),
            str(plan_path),
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode == 0:
        return [], None
    ok, fatal, notice = run_prepare_subprocess_recoverable(proc, step="docs-currency-gate")
    if ok:
        return ([notice] if notice else []), None
    return [], fatal or _parse_subprocess_json(proc)


def run_terminal_prepare_living_docs_gates(
    root: Path, state: dict[str, Any]
) -> list[dict[str, Any]]:
    """Run append-terminal + currency gates; degrade recoverable planning failures (R5)."""
    notices: list[dict[str, Any]] = []
    append_notices, append_fatal = run_living_docs_append_terminal(root)
    if append_fatal:
        fail_from_payload(
            fail,
            append_fatal,
            "living-docs append-terminal failed",
            1,
        )
    notices.extend(append_notices)
    run_tasks_currency_gate(root, state)
    docs_notices, docs_fatal = run_docs_currency_gate_for_prepare(root)
    if docs_fatal:
        fail_from_payload(
            fail,
            docs_fatal,
            "living-doc currency drift",
            1,
            halt="blocked",
            cause="docs-currency:drift",
        )
    notices.extend(docs_notices)
    record_terminal_prepare_degradations(root, state, notices)
    return notices


def run_tasks_currency_gate(root: Path, state: dict[str, Any]) -> None:
    """Hard-block terminal gate when task-list currency diverges (R7 / PRD 067 R4).

    Requires independent corroboration (CI/gate or completion claims) — never
    treat checkbox↔ledger alone as sufficient evidence (no circular proof).
    """
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
    # R4: independent status/gate corroboration
    phases = state.get("phases") or {}
    if not phases:
        return
    corroborated = False
    for meta in phases.values():
        if not isinstance(meta, dict):
            continue
        if meta.get("status") not in ("green-merged", "merge-ready-green"):
            continue
        if meta.get("gateVerdict") in ("green", "pass") or meta.get("ciVerdict") in ("green", "pass"):
            corroborated = True
            break
        slug = meta.get("slug")
        if slug:
            status_path = root / ".cursor" / "sw-deliver-runs" / str(slug) / "status.json"
            if status_path.is_file():
                try:
                    payload = json.loads(status_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    payload = {}
                if payload.get("verdict") in ("merge-ready-green", "green-merged"):
                    gate = (payload.get("gate") or payload.get("checkGate") or {})
                    if isinstance(gate, dict) and gate.get("verdict") in ("green", "pass"):
                        corroborated = True
                        break
                    claims = payload.get("completionClaims") or payload.get("claims")
                    if claims:
                        corroborated = True
                        break
    terminal_ship = state.get("terminalShip") or {}
    if terminal_ship.get("status") in ("gate-green", "local-evidence"):
        corroborated = True
    completed = state.get("completedMerges") or []
    if completed:
        corroborated = True
    if not corroborated:
        fail(
            "terminal currency lacks independent gate/CI corroboration",
            exit_code=1,
            halt="blocked",
            cause="ledger-corroboration-missing",
        )


def resolve_docs_currency_paths(root: Path) -> tuple[Path, Path, Path, Path]:
    from wave_state import load_deliver_state, resolve_state_path

    state = load_deliver_state(root)
    state_path = resolve_state_path(root, state_hint=state if state else None)
    plan_path = root / ".cursor" / "sw-deliver-plan.json"
    return root, root, state_path, plan_path


def ensure_terminal_index_projection(root: Path) -> None:
    """Project INDEX + completion evidence for issue-store before docs-currency (R4/R50)."""
    import contextlib
    import io

    from wave_living_docs import (
        append_completion_store_event,
        derive_index_status,
        living_doc_write_banned,
        read_completion_evidence,
    )
    from wave_state import load_deliver_state
    import planning_index_issue as pii
    import planning_paths as pp

    if not living_doc_write_banned(root):
        return
    state = load_deliver_state(root) or {}
    prd = str(state.get("prd_number") or "").zfill(3)
    if not prd or prd == "000":
        return
    if derive_index_status(state, False) != "complete":
        return
    slug = str((state.get("target") or {}).get("slug") or "") or None
    with contextlib.redirect_stdout(io.StringIO()):
        pii.project_index_status(root, prd, "complete", slug=slug, force_issue_store=True)
        worktree = pp.git_root(root)
        unit_id = pii.resolve_prd_unit_id(root, prd, slug=slug) or pii._unit_id_from_derived_cache(
            worktree, prd, slug=slug
        )
        if unit_id and read_completion_evidence(root, prd) is None:
            notes = str((state.get("completion") or {}).get("notes") or "pre-merge compounding complete")
            append_completion_store_event(
                root,
                prd_id=prd,
                unit_id=unit_id,
                status="complete",
                evidence={"phase": "deliver-terminal", "notes": notes},
            )


def run_docs_currency_gate(root: Path) -> None:
    """Hard-block terminal gate on living-doc drift for the current run (R50/R43)."""
    if os.environ.get("SW_SKIP_DOCS_CURRENCY") == "1":
        return
    ensure_terminal_index_projection(root)
    script = SCRIPT_DIR / "docs-currency-gate.py"
    repo_root, state_root, state_path, plan_path = resolve_docs_currency_paths(root)
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(repo_root),
            str(state_root),
            str(state_path),
            str(plan_path),
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if proc.returncode != 0:
        try:
            err = json.loads(proc.stdout)
        except json.JSONDecodeError:
            err = {"error": proc.stderr.strip() or proc.stdout.strip() or "docs-currency gate failed"}
        fail_from_payload(
            fail,
            err,
            "living-doc currency drift",
            proc.returncode or 1,
            halt="blocked",
            cause="docs-currency:drift",
        )


def run_check_gate(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    script = SCRIPT_DIR / "check-gate.py"
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


def run_terminal_gate_watch(root: Path, pr: str | None) -> tuple[int, dict[str, Any]]:
    """Bounded watch-ci for terminal ship-run gate (PRD 069 R1)."""
    from watch_ci_lib import watch_ci

    watched = watch_ci(root, pr)
    gate = watched.get("gate") if isinstance(watched.get("gate"), dict) else {}
    ec = int(watched.get("gateExitCode", 30))
    verdict = watched.get("verdict")
    if verdict and gate.get("verdict") != verdict:
        gate = {**gate, "verdict": verdict}
    gate = {
        **gate,
        "watchMode": watched.get("mode"),
        "ciWatch": watched.get("ciWatch"),
        "timedOut": watched.get("timedOut"),
    }
    return ec, gate


def _terminal_library_call(fn, *args, **kwargs) -> TerminalOutcome:
    with terminal_library_mode():
        try:
            fn(*args, **kwargs)
        except TerminalExit as exc:
            return exc.outcome
    return TerminalOutcome({"verdict": "fail", "error": "terminal helper returned without outcome"}, 2)


def run_terminal_retro(root: Path, args: list[str]) -> TerminalOutcome:
    return _terminal_library_call(_cmd_terminal_retro_run_body, root, args)


def run_terminal_pr_prepare(
    root: Path, args: list[str], *, dry_run: bool | None = None
) -> TerminalOutcome:
    if dry_run is None:
        dry_run = has_flag(args, "--dry-run") or os.environ.get("SW_DELIVER_DRY_RUN") == "1"
    return _terminal_library_call(_cmd_terminal_pr_prepare_body, root, args, dry_run=dry_run)


def run_terminal_ship_run(root: Path, args: list[str]) -> TerminalOutcome:
    dry_run = has_flag(args, "--dry-run")
    phase_env = clear_phase_env()
    try:
        return _terminal_library_call(_cmd_terminal_ship_run_body, root, args, dry_run=dry_run)
    finally:
        restore_phase_env(phase_env)


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
        fail_from_payload(fail, resolved, "phase-pr-base", 20)
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
            fail_from_payload(fail, out, out.get("reason", "phase-pr-create-failed"), 20)
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
    if not remote_tip and not local_tip:
        fail(f"cannot resolve tip for {target!r} (fetch {host_remote}/{target} first)")

    promotion_tip = local_tip or remote_tip
    if remote_tip and local_tip and is_ancestor(remote_tip, local_tip, top):
        promotion_tip = local_tip
    elif remote_tip:
        promotion_tip = remote_tip
    demotion_tip = remote_tip or local_tip

    phases = state.get("phases") or {}
    promoted: list[str] = []
    demoted: list[str] = []
    skipped: list[str] = []
    advisories: list[str] = []

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
        merged_on_remote = bool(demotion_tip and is_ancestor(phase_sha, demotion_tip, top))
        merged_for_promotion = bool(promotion_tip and is_ancestor(phase_sha, promotion_tip, top))
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
        if merged_for_promotion:
            unpushed_local = bool(local_tip and remote_tip and not merged_on_remote)
            if not dry_run:
                meta["status"] = "green-merged"
                meta["updatedAt"] = utc_now()
                meta["reconciledFrom"] = remote_ref_name if merged_on_remote else target
                if unpushed_local:
                    meta["cause"] = "resume:unpushed-local-merge"
            if unpushed_local:
                advisories.append(slug)
            promoted.append(slug)

    if not dry_run:
        state["phases"] = phases
        state["remoteTargetTip"] = promotion_tip
        state["reconciledAt"] = utc_now()
        save_state(root, state)
        append_log(
            root,
            {
                "event": "resume-reconcile",
                "promoted": promoted,
                "demoted": demoted,
                "groundTip": promotion_tip,
                "promotionTip": promotion_tip,
                "remoteTip": remote_tip,
                "localTip": local_tip,
            },
        )

    payload = {
        "verdict": "pass",
        "action": "resume-reconcile",
        "dry_run": dry_run,
        "target": target,
        "groundTip": promotion_tip,
        "promotionTip": promotion_tip,
        "remoteTip": remote_tip,
        "localTip": local_tip,
        "promoted": promoted,
        "demoted": demoted,
        "skippedGreenMerged": skipped,
        "note": "Promotion uses local tip when ahead; demotion uses remote ground truth (R47/R48)",
    }
    if advisories:
        payload["unpushedLocalMerge"] = advisories
        payload["remediation"] = f"git push {host_remote} {target}"
    emit(payload)


def terminal_pr_body(root: Path, state: dict[str, Any]) -> str:
    phase_lines: list[str] = []
    for record in state.get("mergedPhases") or []:
        slug = record.get("phaseSlug", "?")
        pr = record.get("pr")
        if pr:
            phase_lines.append(f"- {slug}: #{pr}")
        else:
            phase_lines.append(f"- {slug}")
    summary = "Delivered via `/sw-deliver` phase-mode."
    if phase_lines:
        summary += "\n\n## Phase PRs\n\n" + "\n".join(phase_lines)
    summary += "\n\nHuman merge gate — do not auto-merge."
    test_plan = "- [ ] Review phase PR list\n- [ ] Confirm deliver-concurrency fixtures green"
    slug = (state.get("target") or {}).get("slug") or "deliver-wave"
    prd = str(state.get("prd_number") or "050")
    decision = json.dumps(
        {
            "intent": "Terminal deliver wave PR for phase-mode delivery",
            "alternativesRuledOut": ["Direct push to main"],
            "highRiskAreas": ["Merge gate bypass"],
            "taskRefs": [f"prd-{prd.lstrip('0') or prd}"],
        }
    )
    ctx = json.dumps(
        {
            "summary": summary,
            "test_plan": test_plan,
            "prd_slug": slug,
            "decision_log_json": decision,
        }
    )
    render = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "git_template_lib.py"),
            "render",
            "pr-body",
            "--context-json",
            ctx,
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if render.returncode != 0:
        fail(render.stderr.strip() or "terminal PR body render failed", exit_code=20)
    body = render.stdout
    validate = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "git_template_lib.py"),
            "validate",
            "pr-body",
            "--body",
            body,
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    if validate.returncode != 0:
        fail("terminal PR body failed template validation", exit_code=20, detail=validate.stdout.strip())
    return body



TERMINAL_BRANCH_EXISTS = "confirmed-exists"
TERMINAL_BRANCH_ABSENT = "confirmed-absent"
TERMINAL_BRANCH_UNRESOLVABLE = "probe-inconclusive"


def ensure_target_branch_pushed(root: Path, target: str, host_remote: str, top: Path) -> None:
    """Push target branch before remote existence validation (PRD 059 R13)."""
    remote_ref_name = remote_ref(host_remote, target)
    local_tip = resolve_ref(top, target)
    remote_tip = resolve_ref(top, remote_ref_name)
    if remote_tip and local_tip and remote_tip == local_tip:
        return
    push = git_run(["push", "-u", host_remote, target], cwd=top, check=False)
    if push.returncode != 0:
        fail(
            push.stderr.strip() or "git push failed",
            exit_code=push.returncode,
            halt="blocked",
            cause="terminal-ship:push-failed",
        )


def classify_target_branch_existence(root: Path, target: str, host_remote: str, top: Path) -> str:
    """Classify local + remote ref probes into three terminal outcomes (PRD 059 R14)."""
    local_tip = resolve_ref(top, target)
    if not local_tip:
        return TERMINAL_BRANCH_ABSENT
    try:
        remote_exists = probe_remote_ref_exists(root, branch=target, remote=host_remote)
    except (HostProbeInconclusive, HostRateLimited):
        return TERMINAL_BRANCH_UNRESOLVABLE
    if remote_exists:
        return TERMINAL_BRANCH_EXISTS
    return TERMINAL_BRANCH_ABSENT


def halt_terminal_branch_outcome(outcome: str, *, target: str) -> None:
    if outcome == TERMINAL_BRANCH_ABSENT:
        fail(
            f"terminal target branch missing on remote: {target!r}",
            exit_code=20,
            halt="blocked",
            cause="terminal-branch-missing",
            targetBranch=target,
        )
    if outcome == TERMINAL_BRANCH_UNRESOLVABLE:
        fail(
            f"terminal target branch existence probe inconclusive for {target!r}",
            exit_code=20,
            halt="blocked",
            cause="terminal-branch-unresolvable",
            targetBranch=target,
        )


def cmd_terminal_pr_prepare(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run") or os.environ.get("SW_DELIVER_DRY_RUN") == "1"
    phase_env = clear_phase_env()
    try:
        outcome = run_terminal_pr_prepare(root, args, dry_run=dry_run)
    finally:
        restore_phase_env(phase_env)
    emit_outcome(outcome)


def _cmd_terminal_pr_prepare_body(root: Path, args: list[str], *, dry_run: bool) -> None:
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
        title = parse_kv(args, "--title") or commitlint_safe_title(commit_type, slug, prd_number, root=root)
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
            run_terminal_prepare_living_docs_gates(root, state)
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
        run_terminal_prepare_living_docs_gates(root, state)

    prd_number = state.get("prd_number")
    title = parse_kv(args, "--title") or commitlint_safe_title(commit_type, slug, prd_number, root=root)
    body = terminal_pr_body(root, state)

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
    host_remote = remote_name(load_workflow_config(root))
    ensure_target_branch_pushed(root, target, host_remote, top)
    outcome = classify_target_branch_existence(root, target, host_remote, top)
    halt_terminal_branch_outcome(outcome, target=target)

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
    prepare_payload: dict[str, Any] = {
        "verdict": "pass",
        "action": "terminal-pr-prepare",
        "terminalPr": state["terminalPr"],
        "note": "Single <type>/<slug> → main PR; halt at human gate (R23)",
    }
    degraded = state.get("terminalPrepareDegraded")
    if degraded:
        prepare_payload["degraded"] = True
        prepare_payload["terminalPrepareDegraded"] = degraded
        prepare_payload["note"] = (
            "Prepare degraded — gate path continues; not unqualified green (R5)"
        )
    emit(prepare_payload)


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
        elif sub == "gap-capture":
            gc_sub = rest[0] if rest else ""
            gc_rest = rest[1:]
            if gc_sub == "run":
                cmd_terminal_gap_capture_run(root, gc_rest)
            else:
                fail("terminal gap-capture subcommand required: run")
        else:
            fail("terminal subcommand required: pr|gap-capture")
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
