#!/usr/bin/env python3
"""Safe auto-repair for phase-ship hygiene halts (PRD 278 R1–R2, D2, D4)."""
from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from check_gate_lib import GATE_MANIFEST_CACHE_REL, manifest_sha256, persist_gate_manifest_snapshot
from kernel_classification import normalize_step
from status_integrity import resolve_write_head

EVALUATION_PROVENANCE_KEY = "evaluationProvenance"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def phase_ship_resume_command(*, phase_slug: str = "", from_step: str | None = None) -> str:
    slug = phase_slug or os.environ.get("SW_PHASE_SLUG", "").strip()
    cmd = "/sw-ship --phase-mode"
    if from_step:
        cmd += f" --from {from_step}"
    if slug:
        cmd += f"  # phase={slug}"
    return cmd


def tasks_currency_resume_command(root: Path, state: dict[str, Any]) -> str:
    task_list = str(state.get("source_task_list") or os.environ.get("SW_TASK_LIST", "")).strip()
    if task_list:
        return f"/sw-deliver run --task-list {task_list}"
    return "/sw-deliver run"


def blocked_payload(
    cause: str,
    *,
    resume_command: str,
    action: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "verdict": "fail",
        "cause": cause,
        "resumeCommand": resume_command,
    }
    if action:
        payload["action"] = action
    payload.update(extra)
    return payload


def is_forged_gap_check_status(data: dict[str, Any]) -> bool:
    """Binding pass without authoritative evaluation provenance is forged (D4)."""
    if data.get("verdict") != "pass" or not data.get("binding"):
        return False
    prov = data.get(EVALUATION_PROVENANCE_KEY)
    if not isinstance(prov, dict):
        return True
    head = str(data.get("head") or "")
    eval_head = str(prov.get("evaluationHead") or "")
    if head and eval_head and head != eval_head:
        return True
    for key in ("evaluationHead", "evaluatedAt", "source"):
        if not prov.get(key):
            return True
    return False


def _resolve_phase_run_dir(root: Path, phase_slug: str) -> Path:
    canonical = root / ".cursor" / "sw-deliver-runs" / phase_slug
    sw_run = os.environ.get("SW_RUN_DIR", "").strip()
    if sw_run:
        env_path = Path(sw_run)
        if not env_path.is_absolute():
            env_path = (root / env_path).resolve()
        if (env_path / "ship-steps.json").is_file():
            return env_path
        if env_path.name == phase_slug:
            return env_path
    try:
        from wave_state import load_deliver_state
        from phase_status_discovery import resolve_phase_worktree

        state = load_deliver_state(root)
        worktree = resolve_phase_worktree(root, phase_slug, state)
        if worktree is not None:
            wt_run = worktree / ".cursor" / "sw-deliver-runs" / phase_slug
            if (wt_run / "ship-steps.json").is_file():
                return wt_run
    except Exception:
        pass
    return canonical


def discover_authoritative_gap_evaluation(
    root: Path, phase_slug: str, head: str
) -> dict[str, Any] | None:
    """Authoritative gap evaluation at exact phase HEAD — no forged pass (R1/D4)."""
    from gate_evidence import resolve_authoritative_record

    record, _ = resolve_authoritative_record(root, phase_slug, "gap-check", head_sha=head)
    if record and str(record.get("verdict")) == "pass":
        return {
            "source": "gate-evidence",
            "evaluationHead": head,
            "evaluatedAt": str(record.get("timestamp") or utc_now()),
            "gateId": "gap-check",
        }

    run_dir = _resolve_phase_run_dir(root, phase_slug)
    steps_path = run_dir / "ship-steps.json"
    if not steps_path.is_file():
        return None
    try:
        doc = json.loads(steps_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(doc, dict):
        return None
    chain = [normalize_step(str(s)) for s in (doc.get("chain") or [])]
    last = normalize_step(str(doc.get("lastCompletedStep") or ""))
    if "gap-check" not in chain or last not in chain:
        return None
    if chain.index(last) < chain.index("gap-check"):
        return None
    return {
        "source": "ship-steps",
        "evaluationHead": head,
        "evaluatedAt": str(doc.get("updatedAt") or utc_now()),
        "lastCompletedStep": last,
    }


def _load_gap_check_gate():
    import importlib.util

    gate_path = SCRIPT_DIR / "gap-check-gate.py"
    spec = importlib.util.spec_from_file_location("gap_check_gate", gate_path)
    if spec is None or spec.loader is None:
        raise ImportError("gap-check-gate.py unavailable")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def try_auto_repair_gap_check_missing(root: Path, phase_slug: str) -> dict[str, Any]:
    gap_gate = _load_gap_check_gate()
    discover_gap_check_status = gap_gate.discover_gap_check_status
    status_path = gap_gate.status_path
    write_status = gap_gate.write_status
    resolve_phase_write_head = gap_gate.resolve_phase_write_head

    head = resolve_phase_write_head(root, phase_slug) or resolve_write_head(root)
    if not head:
        return blocked_payload(
            "gap-check-missing",
            resume_command=phase_ship_resume_command(phase_slug=phase_slug, from_step="gap-check"),
            action="auto-repair-gap-check-missing",
            error="missing-head",
        )

    _path, existing = discover_gap_check_status(root, phase_slug)
    if existing is not None:
        if is_forged_gap_check_status(existing):
            return blocked_payload(
                "gap-check-forged-pass",
                resume_command=phase_ship_resume_command(phase_slug=phase_slug, from_step="gap-check"),
                action="auto-repair-gap-check-missing",
            )
        if existing.get("verdict") == "pass" and existing.get("binding"):
            return {"verdict": "pass", "action": "auto-repair-gap-check-missing", "note": "already-present"}

    evaluation = discover_authoritative_gap_evaluation(root, phase_slug, head)
    if evaluation is None:
        return blocked_payload(
            "gap-check-missing",
            resume_command=phase_ship_resume_command(phase_slug=phase_slug, from_step="gap-check"),
            action="auto-repair-gap-check-missing",
        )

    out_path = status_path(root, phase_slug)
    doc = write_status(
        out_path,
        "pass",
        cause=None,
        head=head,
        evaluation_provenance=evaluation,
    )
    return {
        "verdict": "pass",
        "action": "auto-repair-gap-check-missing",
        "path": str(out_path),
        EVALUATION_PROVENANCE_KEY: evaluation,
        **doc,
    }


def try_auto_repair_tasks_currency_divergence(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    """Heal checkbox↔ledger drift from authoritative store without inventing completion (R1/D2)."""
    from wave_deliver import phase_entry_currency_check, resync_auto_invocation_blocked
    from wave_deliver_loop import task_list_from, tasks_currency_ok

    task_list = task_list_from(state, plan)
    if not task_list:
        return {"verdict": "pass", "action": "auto-repair-tasks-currency", "note": "no-task-list"}

    ok, cause = tasks_currency_ok(root, state, plan)
    if ok:
        return {"verdict": "pass", "action": "auto-repair-tasks-currency", "note": "already-aligned"}

    if resync_auto_invocation_blocked(state):
        return blocked_payload(
            cause or "tasks-currency-divergence",
            resume_command=tasks_currency_resume_command(root, state),
            action="auto-repair-tasks-currency",
            reason="merge-or-terminal-in-flight",
        )

    resync = phase_entry_currency_check(root, task_list, state=state)
    if isinstance(resync, dict) and resync.get("verdict") == "fail":
        return blocked_payload(
            cause or "tasks-currency-divergence",
            resume_command=tasks_currency_resume_command(root, state),
            action="auto-repair-tasks-currency",
            detail=resync,
        )

    ok_after, cause_after = tasks_currency_ok(root, state, plan)
    if ok_after:
        return {
            "verdict": "pass",
            "action": "auto-repair-tasks-currency",
            "resync": resync,
        }

    return blocked_payload(
        cause_after or cause or "tasks-currency-divergence",
        resume_command=tasks_currency_resume_command(root, state),
        action="auto-repair-tasks-currency",
        resync=resync,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _mirror_gate_manifest_cache(source: Path, dest_root: Path) -> dict[str, str] | None:
    if not source.is_file():
        return None
    try:
        manifest = json.loads(source.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return persist_gate_manifest_snapshot(dest_root, manifest)


def _copy_gate_manifest_cache(source: Path, dest_root: Path) -> dict[str, str] | None:
    if not source.is_file():
        return None
    dest = dest_root / GATE_MANIFEST_CACHE_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    content = source.read_bytes()
    dest.write_bytes(content)
    rel = str(dest.relative_to(dest_root))
    return {"manifestPath": rel, "manifestSha256": manifest_sha256(content)}


def _plugin_root(start: Path) -> Path:
    from gate_evidence import repo_root

    return repo_root(start)


def try_auto_repair_pr_test_plan_manifest(
    root: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Mirror missing orchestrator gate-cache manifest from authoritative evidence (R1)."""
    from wave_deliver_loop import orchestrator_worktree_path

    orch = orchestrator_worktree_path(root, state)
    if orch is None:
        return blocked_payload(
            "prTestPlan-manifest-missing",
            resume_command=tasks_currency_resume_command(root, state),
            action="auto-repair-prTestPlan-manifest",
            error="orchestrator-worktree-missing",
        )

    cache_path = orch / GATE_MANIFEST_CACHE_REL
    if cache_path.is_file():
        return {"verdict": "pass", "action": "auto-repair-prTestPlan-manifest", "note": "already-present"}

    plugin = _plugin_root(SCRIPT_DIR)
    for candidate in (
        root / GATE_MANIFEST_CACHE_REL,
        plugin / "core" / "sw-reference" / "pr-test-plan.manifest.json",
        root / "core" / "sw-reference" / "pr-test-plan.manifest.json",
    ):
        if "sw-gate-cache" in str(candidate):
            refs = _copy_gate_manifest_cache(candidate, orch)
        else:
            refs = _mirror_gate_manifest_cache(candidate, orch)
        if refs is not None:
            return {
                "verdict": "pass",
                "action": "auto-repair-prTestPlan-manifest",
                "mirroredFrom": str(candidate),
                **refs,
            }

    run_id = str(state.get("runId") or os.environ.get("SW_DELIVER_RUN_ID", "")).strip()
    if run_id:
        run_gate = root / ".cursor" / "sw-deliver-runs" / run_id / "gate-evidence" / "check-gate.status.json"
        gate_doc = _read_json(run_gate)
        if gate_doc:
            pr_test_plan = (gate_doc.get("gate") or gate_doc).get("prTestPlan") if isinstance(gate_doc.get("gate"), dict) else gate_doc.get("prTestPlan")
            if isinstance(pr_test_plan, dict):
                path_rel = pr_test_plan.get("manifestPath")
                if path_rel:
                    source = root / str(path_rel)
                    refs = _copy_gate_manifest_cache(source, orch)
                    if refs is not None:
                        return {
                            "verdict": "pass",
                            "action": "auto-repair-prTestPlan-manifest",
                            "mirroredFrom": str(source),
                            **refs,
                        }

    return blocked_payload(
        "prTestPlan-manifest-missing",
        resume_command=tasks_currency_resume_command(root, state),
        action="auto-repair-prTestPlan-manifest",
    )


def ensure_orchestrator_gate_manifest_cache(root: Path, state: dict[str, Any]) -> dict[str, Any] | None:
    """Best-effort repair before terminal/status validation; None when already OK."""
    from check_gate_lib import validate_pr_test_plan_gate
    from wave_deliver_loop import orchestrator_worktree_path

    orch = orchestrator_worktree_path(root, state)
    if orch is None:
        return None
    cache_path = orch / GATE_MANIFEST_CACHE_REL
    if cache_path.is_file():
        slim = {"manifestPath": str(GATE_MANIFEST_CACHE_REL), "manifestSha256": manifest_sha256(cache_path.read_bytes())}
        if validate_pr_test_plan_gate(orch, slim) is None:
            return None
    repair = try_auto_repair_pr_test_plan_manifest(root, state)
    return repair if repair.get("verdict") == "pass" else repair
