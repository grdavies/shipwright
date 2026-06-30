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

BUDGET_REJECTION_THRESHOLD = 3

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



def read_plan_policy(root: Path) -> str:
    from wave_plan_validate import read_config_plan_policy  # noqa: PLC0415

    return read_config_plan_policy(root)


def orchestrator_entry(
    root: Path,
    orchestrator_type: str,
    signal_raw: dict[str, Any],
    *,
    run_id: str | None = None,
    skip_selector: bool = False,
) -> dict[str, Any]:
    policy = read_plan_policy(root)
    if policy == "canonical":
        return {
            "verdict": "pass",
            "planPolicy": "canonical",
            "mode": "canonical",
            "persistedPlan": False,
            "proposedArtifacts": False,
        }
    if orchestrator_type not in EPISODIC_ORCHESTRATORS:
        return {"verdict": "reject", "reason": "proposed entry applies to episodic orchestrators only"}
    from orchestrator_signal_context import capture  # noqa: PLC0415
    from orchestrator_step_plan import canonical_orchestrator_chain  # noqa: PLC0415
    from orchestrator_plan_surfacing import persist_validated_plan, surface_entry  # noqa: PLC0415
    from wave_plan_validate import validate_orchestrator_plan  # noqa: PLC0415

    run = provision(root, orchestrator_type, run_id)
    rid = run["runId"]
    rd = run_dir(root, orchestrator_type, rid)
    captured = capture(orchestrator_type, signal_raw)
    if captured["verdict"] != "pass":
        count = append_plan_rejection(root, orchestrator_type, rid, captured)
        return {"verdict": "reject", "stage": "capture", "detail": captured, "rejectionCount": count}
    signal_context = captured["signal_context"]
    persist_signal_context(root, orchestrator_type, rid, signal_context)
    steps = canonical_orchestrator_chain(root, orchestrator_type)
    proposal = {"steps": steps, "orchestratorType": orchestrator_type}
    validated = validate_orchestrator_plan(
        root,
        proposal,
        orchestrator_type=orchestrator_type,
        signal_context=signal_context,
    )
    if validated.get("verdict") != "pass":
        count = append_plan_rejection(root, orchestrator_type, rid, validated)
        return {
            "verdict": "reject",
            "stage": "plan-validate",
            "detail": validated,
            "rejectionCount": count,
        }
    plan = validated["plan"]
    persist_validated_plan(rd, plan)
    capability_set: dict[str, Any] | None = None
    if not skip_selector:
        from capability_select import normalize_signal_context, select_capabilities  # noqa: PLC0415

        index = json.loads((root / "core" / "sw-reference" / "capability-index.json").read_text(encoding="utf-8"))
        ctx = normalize_signal_context(signal_context)
        capability_set = select_capabilities(index, ctx, repo_root=root)
    surface_entry(
        rd,
        orchestrator_type=orchestrator_type,
        run_id=rid,
        plan_policy="proposed",
        chosen_plan=plan,
        capability_set=capability_set,
        plan_rejections=[],
    )
    return {
        "verdict": "pass",
        "planPolicy": "proposed",
        "mode": "proposed",
        "persistedPlan": True,
        "runId": rid,
        "planPath": str((rd / "orchestrator-step-plan.json").relative_to(root)),
        "summaryPath": str((rd / "episodic-run-summary.json").relative_to(root)),
        "capabilityCount": len((capability_set or {}).get("capabilities") or []),
    }


def append_plan_rejection(
    root: Path,
    orchestrator_type: str,
    run_id: str,
    rejection: dict[str, Any],
) -> int:
    from orchestrator_plan_surfacing import append_rejection  # noqa: PLC0415

    rd = run_dir(root, orchestrator_type, run_id)
    return append_rejection(rd, rejection)


def budget_trip_check(root: Path, orchestrator_type: str, run_id: str) -> dict[str, Any]:
    rd = run_dir(root, orchestrator_type, run_id)
    count = 0
    rej_path = rd / "plan-rejections.json"
    if rej_path.is_file():
        data = json.loads(rej_path.read_text(encoding="utf-8"))
        count = int(data.get("count") or len(data.get("rejections") or []))
    tripped = count >= BUDGET_REJECTION_THRESHOLD
    return {
        "verdict": "halt" if tripped else "pass",
        "rejectionCount": count,
        "threshold": BUDGET_REJECTION_THRESHOLD,
        "tripped": tripped,
    }


def debug_canonical_parity_check(root: Path) -> dict[str, Any]:
    import shutil
    import tempfile

    fix = Path(tempfile.mkdtemp())
    try:
        (fix / ".cursor").mkdir(parents=True)
        (fix / "core" / "sw-reference").mkdir(parents=True)
        shutil.copytree(root / "core" / "sw-reference", fix / "core" / "sw-reference", dirs_exist_ok=True)
        (fix / "scripts").mkdir(exist_ok=True)
        for script in (
            "orchestrator_run.py",
            "orchestrator_signal_context.py",
            "orchestrator_step_plan.py",
            "orchestrator_plan_surfacing.py",
            "orchestrator_guidelines.py",
            "wave_plan_validate.py",
            "wave_json_io.py",
            "kernel_classification.py",
            "guidelines_validate.py",
            "plan_floor_evaluator.py",
            "capability_select.py",
            "capability_index.py",
            "capability_precedence.py",
            "capability_trust.py",
            "capability_run_log.py",
        ):
            shutil.copy2(root / "scripts" / script, fix / "scripts" / script)
        (fix / ".cursor" / "workflow.config.json").write_text(
            '{"orchestration":{"planPolicy":"canonical"}}\n', encoding="utf-8"
        )
        result = orchestrator_entry(
            fix,
            "debug",
            {"signal_type": "error", "related_files": ["src/a.ts"]},
            run_id="canonical-parity-fixture",
        )
        rd = run_dir(fix, "debug", "canonical-parity-fixture")
        proposed_artifacts = (rd / "orchestrator-step-plan.json").exists()
        teardown(fix, "debug", "canonical-parity-fixture")
        ok = (
            result.get("planPolicy") == "canonical"
            and result.get("persistedPlan") is False
            and not proposed_artifacts
        )
        return {"verdict": "pass" if ok else "reject", "entry": result, "proposedArtifacts": proposed_artifacts}
    finally:
        shutil.rmtree(fix, ignore_errors=True)


def debug_proposed_routes_gate_selector_check(root: Path) -> dict[str, Any]:
    policy = read_plan_policy(root)
    if policy != "proposed":
        return {"verdict": "pass", "skipped": True, "reason": "planPolicy not proposed"}
    result = orchestrator_entry(
        root,
        "debug",
        {"signal_type": "error", "related_files": ["src/a.ts"], "sentry_ref": "evt-1"},
        run_id="proposed-route-fixture",
    )
    rd = run_dir(root, "debug", "proposed-route-fixture")
    ok = (
        result.get("verdict") == "pass"
        and (rd / "orchestrator-step-plan.json").is_file()
        and (rd / "episodic-run-summary.json").is_file()
        and result.get("capabilityCount", 0) >= 0
    )
    summary = {}
    if (rd / "episodic-run-summary.json").is_file():
        summary = json.loads((rd / "episodic-run-summary.json").read_text(encoding="utf-8"))
    teardown(root, "debug", "proposed-route-fixture")
    return {
        "verdict": "pass" if ok else "reject",
        "entry": result,
        "summaryHasPlan": bool(summary.get("chosenPlan")),
        "summaryHasCapabilities": "capabilitySet" in summary,
    }


def debug_r21_surfacing_check(root: Path) -> dict[str, Any]:
    result = orchestrator_entry(
        root,
        "debug",
        {"signal_type": "error", "related_files": ["src/a.ts"]},
        run_id="r21-surfacing-fixture",
    )
    rd = run_dir(root, "debug", "r21-surfacing-fixture")
    summary = json.loads((rd / "episodic-run-summary.json").read_text(encoding="utf-8"))
    teardown(root, "debug", "r21-surfacing-fixture")
    ok = (
        result.get("verdict") == "pass"
        and summary.get("chosenPlan")
        and "capabilitySet" in summary
        and isinstance(summary.get("planRejections"), list)
    )
    return {"verdict": "pass" if ok else "reject", "summaryKeys": sorted(summary.keys())}


def debug_budget_trip_simulate(root: Path) -> dict[str, Any]:
    run = provision(root, "debug", "budget-trip-fixture")
    rid = run["runId"]
    for _ in range(BUDGET_REJECTION_THRESHOLD):
        append_plan_rejection(root, "debug", rid, {"verdict": "reject", "reasons": ["fixture"]})
    trip = budget_trip_check(root, "debug", rid)
    teardown(root, "debug", rid)
    return trip


def doc_canonical_parity_check(root: Path) -> dict[str, Any]:
    from orchestrator_step_plan import canonical_orchestrator_chain  # noqa: PLC0415
    from variance_probe import probe_orchestrator  # noqa: PLC0415
    from wave_plan_validate import validate_orchestrator_plan  # noqa: PLC0415

    probe = probe_orchestrator(root, "doc")
    steps = list(canonical_orchestrator_chain(root, "doc"))
    validated = validate_orchestrator_plan(
        root,
        {"steps": steps, "orchestratorType": "doc"},
        orchestrator_type="doc",
        signal_context=None,
    )
    policy = read_plan_policy(root)
    ok = (
        probe.get("adoptionMode") == "consistency-only"
        and probe.get("proposedPackDeferred") is True
        and probe.get("defaultsConsistencyOnly") is True
        and probe.get("canonicalEquivProposed") is True
        and validated.get("verdict") == "pass"
        and policy in {"canonical", "proposed"}
    )
    return {
        "verdict": "pass" if ok else "reject",
        "probe": probe,
        "validated": validated.get("verdict"),
        "planPolicy": policy,
        "stepCount": len(steps),
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
    if cmd == "entry":
        orch = parse_kv(rest, "--orchestrator-type")
        run_id = parse_kv(rest, "--run-id")
        raw_path = parse_kv(rest, "--input")
        if not orch:
            fail("--orchestrator-type required")
        raw: dict[str, Any] = {}
        if raw_path:
            p = Path(raw_path)
            raw = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else json.loads(raw_path)
        emit(orchestrator_entry(root, orch, raw, run_id=run_id))
    if cmd == "canonical-parity-check":
        orch = parse_kv(rest, "--orchestrator-type") or "debug"
        if orch == "debug":
            emit(debug_canonical_parity_check(root))
        elif orch == "doc":
            emit(doc_canonical_parity_check(root))
        else:
            fail(f"canonical-parity-check unsupported for orchestrator: {orch!r}")
    if cmd == "proposed-routes-check":
        emit(debug_proposed_routes_gate_selector_check(root))
    if cmd == "r21-surfacing-check":
        emit(debug_r21_surfacing_check(root))
    if cmd == "budget-trip-check":
        emit(debug_budget_trip_simulate(root))
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
