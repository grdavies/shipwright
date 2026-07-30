#!/usr/bin/env python3
"""Triage-owner notification for red nightly CI lanes (PRD 083 R8)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_gap_capture as pgc
import suite_registry as sr
from _sw.cli import run_module_main
from closeout_ci import DEFAULT_SLO_OWNER

NIGHTLY_PLAN_ID = "scheduled-full-plus-integration"
DEFAULT_JOB_NAME = "verify-scheduled-full-plus-integration"


def repo_root(start: Path | None = None) -> Path:
    start = start or SCRIPT_DIR
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def resolve_triage_owner(root: Path, *, plan_id: str = NIGHTLY_PLAN_ID) -> str:
    """Resolve responsible owner from suite-registry plan metadata."""
    try:
        registry = sr.load_registry(root)
        plan = (registry.get("plans") or {}).get(plan_id) or {}
        owner = str(plan.get("triageOwner") or "").strip()
        if owner:
            return owner
    except (FileNotFoundError, ValueError, OSError):
        pass
    return DEFAULT_SLO_OWNER


def build_payload_from_env() -> dict[str, Any]:
    return {
        "job": (os.environ.get("GITHUB_JOB") or DEFAULT_JOB_NAME).strip() or DEFAULT_JOB_NAME,
        "workflowRunId": (os.environ.get("GITHUB_RUN_ID") or "").strip(),
        "repository": (os.environ.get("GITHUB_REPOSITORY") or "").strip(),
        "eventName": (os.environ.get("GITHUB_EVENT_NAME") or "").strip(),
        "workflow": (os.environ.get("GITHUB_WORKFLOW") or "").strip(),
        "sha": (os.environ.get("GITHUB_SHA") or "").strip(),
        "ref": (os.environ.get("GITHUB_REF") or "").strip(),
        "conclusion": "failure",
        "notifiedAt": utc_now(),
    }


def normalize_payload(raw: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(raw or {})
    job = str(payload.get("job") or DEFAULT_JOB_NAME).strip() or DEFAULT_JOB_NAME
    payload["job"] = job
    payload.setdefault("conclusion", "failure")
    if not payload.get("notifiedAt"):
        payload["notifiedAt"] = utc_now()
    return payload


def _signal_id(payload: dict[str, Any]) -> str:
    run_id = str(payload.get("workflowRunId") or "unknown").strip() or "unknown"
    job = str(payload.get("job") or DEFAULT_JOB_NAME)
    return f"nightly-failure:{job}:{run_id}"


def _build_gap_copy(owner: str, payload: dict[str, Any]) -> tuple[str, str, str]:
    job = str(payload.get("job") or DEFAULT_JOB_NAME)
    title = f"Nightly lane {job} failed"
    run_id = str(payload.get("workflowRunId") or "unknown")
    repo = str(payload.get("repository") or "unknown")
    sha = str(payload.get("sha") or "")[:12]
    problem = (
        f"The scheduled nightly lane `{job}` failed (owner: {owner}). "
        f"Run {run_id} on `{repo}` requires triage."
    )
    context_lines = [
        f"- Owner: `{owner}`",
        f"- Repository: `{repo}`",
        f"- Workflow run: `{run_id}`",
        f"- Event: `{payload.get('eventName') or 'schedule'}`",
        f"- Ref: `{payload.get('ref') or 'n/a'}`",
    ]
    if sha:
        context_lines.append(f"- SHA: `{sha}`")
    context = "\n".join(context_lines)
    return title, problem, context


def notify_nightly_failure(
    root: Path,
    payload: dict[str, Any],
    *,
    dry_run: bool = False,
    dedupe: bool = True,
) -> dict[str, Any]:
    normalized = normalize_payload(payload)
    owner = resolve_triage_owner(root)
    title, problem, context = _build_gap_copy(owner, normalized)
    signal_id = _signal_id(normalized)
    capture = pgc.capture_gap(
        root,
        signal_id=signal_id,
        title=title,
        problem=problem,
        context=context,
        dry_run=dry_run,
        dedupe=dedupe,
        authoritative=True,
    )
    return {
        "verdict": "pass",
        "action": "nightly-failure-notify",
        "owner": owner,
        "signalId": signal_id,
        "job": normalized["job"],
        "capture": capture,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="File a planning-store gap and name triage owner for a red nightly lane (PRD 083 R8)."
    )
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--payload-file", help="JSON file with failed-run payload")
    parser.add_argument("--job", default="", help="CI job name")
    parser.add_argument("--workflow-run-id", default="", help="GitHub workflow run id")
    parser.add_argument("--repository", default="", help="owner/repo slug")
    parser.add_argument("--dry-run", action="store_true", help="Gap capture dry-run (no store writes)")
    parser.add_argument("--no-dedupe", action="store_true", help="Disable open-gap dedupe")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    root = repo_root(Path(args.root))
    if args.payload_file:
        try:
            raw = json.loads(Path(args.payload_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            fail("invalid-payload-file", error=str(exc))
        if not isinstance(raw, dict):
            fail("invalid-payload-shape")
        payload = raw
    else:
        payload = build_payload_from_env()
    if args.job:
        payload["job"] = args.job
    if args.workflow_run_id:
        payload["workflowRunId"] = args.workflow_run_id
    if args.repository:
        payload["repository"] = args.repository

    try:
        result = notify_nightly_failure(
            root,
            payload,
            dry_run=bool(args.dry_run),
            dedupe=not bool(args.no_dedupe),
        )
    except SystemExit:
        raise
    except Exception as exc:
        owner = resolve_triage_owner(root)
        emit(
            {
                "verdict": "fail",
                "error": str(exc),
                "owner": owner,
                "action": "nightly-failure-notify",
            },
            20,
        )
    emit(result)
    return 0


if __name__ == "__main__":
    run_module_main(main)
