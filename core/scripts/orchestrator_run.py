#!/usr/bin/env python3
"""Episodic orchestrator run dirs + cross-orchestrator isolation (PRD 024 TR6, R37)."""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wave_json_io import write_json

EPISODIC_ORCHESTRATORS = frozenset({"debug", "feedback"})
RUN_ROOTS: dict[str, str] = {
    "debug": "sw-debug-runs",
    "feedback": "sw-feedback-runs",
}
DELIVER_PROTECTED_PREFIXES = (
    "sw-deliver-state",
    "sw-deliver-",
    "sw-deliver-runs",
)
RESUME_ARTIFACT_NAMES = frozenset(
    {
        "crash-resume.json",
        "durable-run-record.json",
        "resume-state.json",
    }
)


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


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]


def run_root(root: Path, orchestrator_type: str) -> Path:
    rel = RUN_ROOTS.get(orchestrator_type)
    if not rel:
        fail(f"no episodic run root for orchestrator: {orchestrator_type!r}")
    return root / ".cursor" / rel


def run_dir(root: Path, orchestrator_type: str, run_id: str) -> Path:
    return run_root(root, orchestrator_type) / run_id


def is_deliver_protected_path(root: Path, target: Path) -> bool:
    try:
        rel = target.resolve().relative_to((root / ".cursor").resolve())
    except ValueError:
        return False
    parts = rel.parts
    if not parts:
        return False
    head = parts[0]
    if head == "sw-deliver-runs":
        return True
    if head.startswith(DELIVER_PROTECTED_PREFIXES):
        return True
    return False


def assert_write_allowed(root: Path, orchestrator_type: str, target: Path) -> dict[str, Any]:
    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        return {"verdict": "pass", "allowed": True}
    if is_deliver_protected_path(root, target):
        return {
            "verdict": "reject",
            "allowed": False,
            "reason": f"{orchestrator_type} run cannot write deliver-scoped path: {target}",
        }
    allowed_root = run_root(root, orchestrator_type)
    try:
        target.resolve().relative_to(allowed_root.resolve())
        return {"verdict": "pass", "allowed": True}
    except ValueError:
        return {
            "verdict": "reject",
            "allowed": False,
            "reason": f"{orchestrator_type} run write outside namespaced scratch: {target}",
        }


def provision(root: Path, orchestrator_type: str, run_id: str | None = None) -> dict[str, Any]:
    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        fail(f"provision applies to episodic orchestrators only: {orchestrator_type!r}")
    rid = run_id or new_run_id()
    path = run_dir(root, orchestrator_type, rid)
    path.mkdir(parents=True, exist_ok=True)
    meta = {
        "orchestratorType": orchestrator_type,
        "runId": rid,
        "durability": "episodic",
        "crashResume": False,
        "provisionedAt": utc_now(),
    }
    write_json(path / "run-meta.json", meta)
    os.chmod(path, 0o700)
    return {"verdict": "pass", "runId": rid, "path": str(path.relative_to(root)), "meta": meta}


def persist_signal_context(
    root: Path,
    orchestrator_type: str,
    run_id: str,
    signal_context: dict[str, Any],
) -> Path:
    if orchestrator_type in EPISODIC_ORCHESTRATORS:
        base = run_dir(root, orchestrator_type, run_id)
        base.mkdir(parents=True, exist_ok=True)
        target = base / "signal_context.json"
    else:
        base = root / ".cursor" / "sw-doc-runs" / run_id
        base.mkdir(parents=True, exist_ok=True)
        target = base / "signal_context.json"
    guard = assert_write_allowed(root, orchestrator_type, target)
    if not guard.get("allowed"):
        fail(guard.get("reason", "write refused"))
    write_json(target, signal_context)
    return target


def write_episodic_summary(
    root: Path,
    orchestrator_type: str,
    run_id: str,
    summary: dict[str, Any],
) -> Path:
    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        fail("episodic summary applies to debug/feedback only")
    path = run_dir(root, orchestrator_type, run_id)
    path.mkdir(parents=True, exist_ok=True)
    target = path / "episodic-run-summary.json"
    guard = assert_write_allowed(root, orchestrator_type, target)
    if not guard.get("allowed"):
        fail(guard.get("reason", "write refused"))
    payload = {
        "version": 1,
        "orchestratorType": orchestrator_type,
        "runId": run_id,
        "durability": "episodic",
        "writtenAt": utc_now(),
        **summary,
    }
    write_json(target, payload)
    return target


def assert_no_durable_resume(root: Path, orchestrator_type: str, run_id: str) -> dict[str, Any]:
    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        return {"verdict": "pass", "applicable": False, "reason": "deliver/doc-scoped resume applies elsewhere"}
    path = run_dir(root, orchestrator_type, run_id)
    violations: list[str] = []
    for name in RESUME_ARTIFACT_NAMES:
        if (path / name).exists():
            violations.append(name)
    meta_path = path / "run-meta.json"
    if meta_path.is_file():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("crashResume") is True:
            violations.append("run-meta.crashResume")
    return {
        "verdict": "pass" if not violations else "reject",
        "applicable": True,
        "resumeRevalidatesPlanPolicyMode": "N/A",
        "violations": violations,
    }


def teardown(root: Path, orchestrator_type: str, run_id: str) -> dict[str, Any]:
    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        fail("teardown applies to episodic orchestrators only")
    path = run_dir(root, orchestrator_type, run_id)
    if not path.exists():
        return {"verdict": "pass", "action": "noop", "path": str(path.relative_to(root))}
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_dir():
            child.rmdir()
    path.rmdir()
    return {"verdict": "pass", "action": "teardown", "path": str(path.relative_to(root))}


def cross_orchestrator_isolation_check(root: Path) -> dict[str, Any]:
    debug = provision(root, "debug", "isolation-fixture")
    run_id = debug["runId"]
    deliver_state = root / ".cursor" / "sw-deliver-state.fixture-slug.json"
    guard = assert_write_allowed(root, "debug", deliver_state)
    selector_path = root / ".cursor" / "sw-deliver-runs" / "fixture-phase" / "phase-step-plan.json"
    selector_guard = assert_write_allowed(root, "debug", selector_path)
    teardown(root, "debug", run_id)
    ok = guard.get("verdict") == "reject" and selector_guard.get("verdict") == "reject"
    return {
        "verdict": "pass" if ok else "reject",
        "debugDeliverStateWrite": guard,
        "debugSelectorWrite": selector_guard,
    }


def episodic_model_check(root: Path, orchestrator_type: str) -> dict[str, Any]:
    from orchestrator_signal_context import capture  # noqa: PLC0415
    from orchestrator_step_plan import canonical_orchestrator_chain  # noqa: PLC0415

    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        fail(f"episodic model check applies to debug/feedback: {orchestrator_type!r}")
    run = provision(root, orchestrator_type)
    run_id = run["runId"]
    raw = (
        {"signal_type": "error", "related_files": ["src/app.ts"], "sentry_ref": "issue-1"}
        if orchestrator_type == "debug"
        else {"source_class": "production", "invocation": "human", "route": "debug"}
    )
    captured = capture(orchestrator_type, raw)
    if captured["verdict"] != "pass":
        return {"verdict": "reject", "stage": "capture", "detail": captured}
    persist_signal_context(root, orchestrator_type, run_id, captured["signal_context"])
    steps = canonical_orchestrator_chain(root, orchestrator_type)
    proposal = {"steps": steps, "orchestratorType": orchestrator_type}
    from wave_plan_validate import validate_orchestrator_plan  # noqa: PLC0415

    validated = validate_orchestrator_plan(
        root,
        proposal,
        orchestrator_type=orchestrator_type,
        signal_context=captured["signal_context"],
    )
    summary_path = write_episodic_summary(
        root,
        orchestrator_type,
        run_id,
        {
            "planPolicy": "proposed",
            "chosenPlan": validated.get("plan"),
            "capabilitySet": [],
            "planRejections": [],
        },
    )
    resume = assert_no_durable_resume(root, orchestrator_type, run_id)
    summary_exists = summary_path.is_file()
    teardown(root, orchestrator_type, run_id)
    ok = (
        validated.get("verdict") == "pass"
        and resume.get("verdict") == "pass"
        and summary_exists
        and resume.get("resumeRevalidatesPlanPolicyMode") == "N/A"
    )
    return {
        "verdict": "pass" if ok else "reject",
        "validated": validated.get("verdict"),
        "resume": resume,
        "summary": str(summary_path.relative_to(root)),
    }


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        emit({"usage": "orchestrator_run.py <repo> <provision|teardown|isolation-check|episodic-check|assert-write> ..."})
    root = Path(args[0]).resolve()
    cmd = args[1]
    rest = args[2:]
    if cmd == "provision":
        orch = parse_kv(rest, "--orchestrator-type")
        run_id = parse_kv(rest, "--run-id")
        if not orch:
            fail("--orchestrator-type required")
        emit(provision(root, orch, run_id))
    if cmd == "teardown":
        orch = parse_kv(rest, "--orchestrator-type")
        run_id = parse_kv(rest, "--run-id")
        if not orch or not run_id:
            fail("--orchestrator-type and --run-id required")
        emit(teardown(root, orch, run_id))
    if cmd == "isolation-check":
        emit(cross_orchestrator_isolation_check(root))
    if cmd == "episodic-check":
        orch = parse_kv(rest, "--orchestrator-type")
        if not orch:
            fail("--orchestrator-type required")
        emit(episodic_model_check(root, orch))
    if cmd == "assert-write":
        orch = parse_kv(rest, "--orchestrator-type")
        target_raw = parse_kv(rest, "--target")
        if not orch or not target_raw:
            fail("--orchestrator-type and --target required")
        result = assert_write_allowed(root, orch, Path(target_raw))
        emit(result, exit_code=0 if result.get("allowed") else 20)
    fail(f"unknown command: {cmd!r}")


if __name__ == "__main__":
    main()
