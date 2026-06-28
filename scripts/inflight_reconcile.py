#!/usr/bin/env python3
"""Self-heal / staleness reconcile for committed inFlight tuples (PRD 032 R3/R4)."""
from __future__ import annotations

import getpass
import json
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_index_gen as pig  # noqa: E402
from inflight_signal import (  # noqa: E402
    InflightTuple,
    is_run_live,
    read_tuples,
    run_id_from_slug,
    write_tuples,
)
from wave_json_io import read_json, write_json  # noqa: E402
from wave_state import enumerate_scoped_runs  # noqa: E402

DEFAULT_STALENESS_TTL_HOURS = 72.0
AUDIT_REL = ".cursor/inflight-reconcile-audit.jsonl"


@dataclass(frozen=True)
class TupleAssessment:
    unit_id: str
    run_id: str
    branch: str | None
    branch_missing: bool
    run_live: bool
    run_in_registry: bool
    verdict: str
    clearable: bool
    clear_reason: str | None
    warnings: tuple[str, ...]


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def actor_id() -> str:
    return f"{getpass.getuser()}@{socket.gethostname()}"


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


def load_workflow_config(root: Path) -> dict[str, Any]:
    for candidate in (root / ".cursor/workflow.config.json", root / "workflow.config.json"):
        if candidate.is_file():
            try:
                return read_json(candidate)
            except Exception:
                return {}
    return {}


def staleness_ttl_hours(root: Path) -> float:
    cfg = load_workflow_config(root)
    planning = cfg.get("planning") if isinstance(cfg.get("planning"), dict) else {}
    in_flight = planning.get("inFlight") if isinstance(planning.get("inFlight"), dict) else {}
    raw = in_flight.get("stalenessTtlHours", DEFAULT_STALENESS_TTL_HOURS)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return DEFAULT_STALENESS_TTL_HOURS


def audit_path(root: Path) -> Path:
    return root / AUDIT_REL


def append_audit(root: Path, entry: dict[str, Any], *, dry_run: bool = False) -> None:
    if dry_run:
        return
    path = audit_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def slug_from_run_id(run_id: str) -> str | None:
    if run_id.startswith("deliver-"):
        return run_id.removeprefix("deliver-")
    return None


def branch_exists(root: Path, branch: str | None) -> bool:
    if not branch:
        return False
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"refs/heads/{branch}"],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def run_id_in_registry(root: Path, run_id: str) -> bool:
    for run in enumerate_scoped_runs(root):
        slug = str(run.get("slug") or "")
        if slug and run_id_from_slug(slug) == run_id:
            return True
    cursor = root / ".cursor"
    if not cursor.is_dir():
        return False
    for path in cursor.glob("sw-deliver-state.*.json"):
        try:
            data = read_json(path)
        except Exception:
            continue
        lease = data.get("inflightLease") or {}
        if lease.get("runId") == run_id:
            return True
    return False


def deliver_state_path(root: Path, run_id: str) -> Path | None:
    slug = slug_from_run_id(run_id)
    if not slug:
        return None
    path = root / ".cursor" / f"sw-deliver-state.{slug}.json"
    return path if path.is_file() else None


def deliver_state_age_hours(root: Path, run_id: str) -> float | None:
    path = deliver_state_path(root, run_id)
    if path is None:
        return None
    return (time.time() - path.stat().st_mtime) / 3600.0


def assess_tuple(
    root: Path,
    unit_id: str,
    tup: InflightTuple,
    *,
    ttl_hours: float,
) -> TupleAssessment:
    branch = tup.branch
    branch_missing = not branch_exists(root, branch) if branch else True
    run_live = is_run_live(root, tup.run_id)
    in_registry = run_id_in_registry(root, tup.run_id)
    warnings: list[str] = []
    verdict = "healthy"
    clearable = False
    clear_reason: str | None = None

    if branch_missing and branch:
        warnings.append(f"implementing branch missing: {branch}")

    if not branch_missing:
        if not run_live:
            verdict = "warn-stale-run"
            warnings.append("run not live but branch still exists")
        return TupleAssessment(
            unit_id=unit_id,
            run_id=tup.run_id,
            branch=branch,
            branch_missing=branch_missing,
            run_live=run_live,
            run_in_registry=in_registry,
            verdict=verdict,
            clearable=False,
            clear_reason=None,
            warnings=tuple(warnings),
        )

    if run_live:
        return TupleAssessment(
            unit_id=unit_id,
            run_id=tup.run_id,
            branch=branch,
            branch_missing=True,
            run_live=True,
            run_in_registry=in_registry,
            verdict="warn-live-branch-missing",
            clearable=False,
            clear_reason=None,
            warnings=tuple([*warnings, "live run-state with missing branch; not clearing (R3)"]),
        )

    if not in_registry:
        state_path = deliver_state_path(root, tup.run_id)
        if state_path is None:
            clearable = True
            verdict = "clear-ttl"
            clear_reason = "orphan-tuple-no-registry-no-porcelain-state"
        else:
            age = deliver_state_age_hours(root, tup.run_id)
            if age is not None and age >= ttl_hours:
                clearable = True
                verdict = "clear-ttl"
                clear_reason = "orphan-tuple-stale-porcelain-state"
            else:
                verdict = "warn-ttl-pending"
                warnings.append(
                    f"orphan tuple awaiting TTL ({age or 0:.1f}h < {ttl_hours}h configured)"
                )
        return TupleAssessment(
            unit_id=unit_id,
            run_id=tup.run_id,
            branch=branch,
            branch_missing=True,
            run_live=False,
            run_in_registry=False,
            verdict=verdict,
            clearable=clearable,
            clear_reason=clear_reason,
            warnings=tuple(warnings),
        )

    clearable = True
    verdict = "clear-terminal"
    clear_reason = "terminal-run-state-and-missing-branch"
    return TupleAssessment(
        unit_id=unit_id,
        run_id=tup.run_id,
        branch=branch,
        branch_missing=True,
        run_live=False,
        run_in_registry=True,
        verdict=verdict,
        clearable=clearable,
        clear_reason=clear_reason,
        warnings=tuple(warnings),
    )


def git_commit_inflight(root: Path, unit_id: str, dry_run: bool) -> str | None:
    rel = pig.index_rel(root)
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain", "--", rel],
        text=True,
        capture_output=True,
    )
    if not proc.stdout.strip():
        return None
    if dry_run:
        return "dry-run"
    env = {**dict(__import__("os").environ), "SW_INDEX_REGION_WRITER": "reconcile"}
    subprocess.run(["git", "-C", str(root), "add", rel], check=True, env=env)
    msg = f"chore(planning): reconcile inFlight clear for {unit_id}"
    proc = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", msg],
        text=True,
        capture_output=True,
        env=env,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or proc.stdout.strip() or "inflight reconcile commit failed")
    sha_proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        capture_output=True,
        check=True,
    )
    return sha_proc.stdout.strip()


def cmd_reconcile(root: Path, args: list[str]) -> None:
    from wave_living_doc_lock import living_doc_write_lock

    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")
    unit_filter = parse_kv(args, "--unit")
    ttl_hours = staleness_ttl_hours(root)
    tuples = read_tuples(root)
    if unit_filter:
        if unit_filter not in tuples:
            emit(
                {
                    "verdict": "pass",
                    "action": "inflight-reconcile",
                    "unit": unit_filter,
                    "tuple": None,
                    "assessments": [],
                    "cleared": [],
                    "warnings": [],
                    "ttlHours": ttl_hours,
                    "dryRun": dry_run,
                }
            )
        tuples = {unit_filter: tuples[unit_filter]}

    assessments: list[dict[str, Any]] = []
    cleared: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    to_clear: list[str] = []

    for unit_id, tup in sorted(tuples.items()):
        assessment = assess_tuple(root, unit_id, tup, ttl_hours=ttl_hours)
        assessments.append(
            {
                "unit": assessment.unit_id,
                "runId": assessment.run_id,
                "branch": assessment.branch,
                "branchMissing": assessment.branch_missing,
                "runLive": assessment.run_live,
                "runInRegistry": assessment.run_in_registry,
                "verdict": assessment.verdict,
                "clearable": assessment.clearable,
                "clearReason": assessment.clear_reason,
                "warnings": list(assessment.warnings),
            }
        )
        if assessment.warnings:
            warnings.append({"unit": unit_id, "messages": list(assessment.warnings)})
        if assessment.clearable:
            to_clear.append(unit_id)

    commit_sha: str | None = None
    if to_clear:
        with living_doc_write_lock(root, target=None, holder="inflight-reconcile"):
            current = read_tuples(root)
            modified = False
            for unit_id in to_clear:
                assessment = next(a for a in assessments if a["unit"] == unit_id)
                if unit_id in current:
                    del current[unit_id]
                    modified = True
                append_audit(
                    root,
                    {
                        "action": "auto-clear",
                        "unit": unit_id,
                        "runId": assessment["runId"],
                        "reason": assessment["clearReason"],
                        "who": actor_id(),
                        "when": utc_now(),
                        "verdict": assessment["verdict"],
                    },
                    dry_run=dry_run,
                )
                cleared.append(
                    {
                        "unit": unit_id,
                        "runId": assessment["runId"],
                        "reason": assessment["clearReason"],
                        "verdict": assessment["verdict"],
                    }
                )
            if modified:
                write_tuples(root, current, dry_run=dry_run)
            if not dry_run and do_commit and modified:
                commit_sha = git_commit_inflight(root, ",".join(to_clear), dry_run=False)

    emit(
        {
            "verdict": "pass",
            "action": "inflight-reconcile",
            "assessments": assessments,
            "cleared": cleared,
            "warnings": warnings,
            "ttlHours": ttl_hours,
            "commit": commit_sha,
            "dryRun": dry_run,
        }
    )


def cmd_manual_clear(root: Path, args: list[str]) -> None:
    from wave_living_doc_lock import living_doc_write_lock

    unit_id = parse_kv(args, "--unit") or (args[0] if args and not args[0].startswith("-") else None)
    reason = parse_kv(args, "--reason")
    dry_run = has_flag(args, "--dry-run")
    do_commit = has_flag(args, "--commit")
    if not unit_id:
        fail("--unit <id> required")
    if not reason:
        fail("--reason required for manual clear-inflight escape hatch")

    tuples = read_tuples(root)
    tup = tuples.get(unit_id)
    if not tup:
        emit(
            {
                "verdict": "pass",
                "action": "clear-inflight",
                "unit": unit_id,
                "tuple": None,
                "cleared": False,
                "reason": reason,
                "dryRun": dry_run,
            }
        )

    commit_sha: str | None = None
    with living_doc_write_lock(root, target=None, holder="clear-inflight"):
        current = read_tuples(root)
        if unit_id in current:
            del current[unit_id]
            write_tuples(root, current, dry_run=dry_run)
        append_audit(
            root,
            {
                "action": "manual-clear",
                "unit": unit_id,
                "runId": tup.run_id if tup else None,
                "reason": reason,
                "who": actor_id(),
                "when": utc_now(),
            },
            dry_run=dry_run,
        )
        if not dry_run and do_commit:
            commit_sha = git_commit_inflight(root, unit_id, dry_run=False)

    emit(
        {
            "verdict": "pass",
            "action": "clear-inflight",
            "unit": unit_id,
            "runId": tup.run_id if tup else None,
            "cleared": True,
            "reason": reason,
            "commit": commit_sha,
            "dryRun": dry_run,
        }
    )


def cmd_assess(root: Path, args: list[str]) -> None:
    unit_id = parse_kv(args, "--unit")
    ttl_hours = staleness_ttl_hours(root)
    tuples = read_tuples(root)
    if unit_id:
        if unit_id not in tuples:
            fail(f"no inFlight tuple for unit: {unit_id}", exit_code=1)
        items = {unit_id: tuples[unit_id]}
    else:
        items = tuples
    out = [
        assess_tuple(root, uid, tup, ttl_hours=ttl_hours).__dict__ for uid, tup in sorted(items.items())
    ]
    emit({"verdict": "pass", "action": "inflight-assess", "ttlHours": ttl_hours, "assessments": out})


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        fail("usage: inflight_reconcile.py <repo-root> <command> [options]")
    root = Path(args[0]).resolve()
    rest = args[1:]
    if not rest:
        fail("subcommand required: reconcile|assess|manual-clear")
    cmd = rest[0]
    tail = rest[1:]
    if cmd == "reconcile":
        cmd_reconcile(root, tail)
    elif cmd == "assess":
        cmd_assess(root, tail)
    elif cmd == "manual-clear":
        cmd_manual_clear(root, tail)
    else:
        fail(f"unknown subcommand: {cmd}")


if __name__ == "__main__":
    main()
