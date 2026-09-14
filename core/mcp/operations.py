"""Bounded MCP application operations — shared with CLI equivalents (PRD 349 R39–R40)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

_REPO = Path(__file__).resolve().parents[2]
_CORE = _REPO / "core"
_SCRIPTS = _REPO / "scripts"
for _p in (_REPO, _CORE, _SCRIPTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

ALLOWED_OPERATIONS: frozenset[str] = frozenset(
    {
        "status",
        "context_retrieve",
        "task_progress",
        "gap_capture",
        "evidence_register",
        "handoff_export",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status(*, root: Path, run_id: str | None = None, **_: Any) -> dict[str, Any]:
    """CLI-equivalent status summary including pending cross-host transitions (R35)."""
    from handoff.acknowledgement import list_pending_transitions

    pending = list_pending_transitions(root, run_id=run_id)
    ship_steps = None
    run_dir_env = os.environ.get("SW_RUN_DIR", "").strip()
    if run_dir_env:
        steps_path = Path(run_dir_env) / "ship-steps.json"
        if steps_path.is_file():
            try:
                ship_steps = json.loads(steps_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                ship_steps = None
    return {
        "ok": True,
        "operation": "status",
        "root": str(root),
        "pendingTransitions": pending,
        "shipSteps": ship_steps,
        "observedAt": _utc_now(),
    }


def context_retrieve(
    *,
    root: Path,
    unit_id: str | None = None,
    paths: list[str] | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Retrieve bounded workspace context (paths + allowlist metadata)."""
    from handoff.readers import read_allowlist_rules

    selected: dict[str, Any] = {}
    for rel in paths or []:
        path = (root / rel).resolve()
        if not str(path).startswith(str(root.resolve())):
            continue
        if path.is_file():
            selected[rel] = path.read_text(encoding="utf-8")[:16_384]
    try:
        allowlist_rules = list(read_allowlist_rules(root) or [])
    except Exception:
        allowlist_rules = []
    return {
        "ok": True,
        "operation": "context_retrieve",
        "unitId": unit_id,
        "files": selected,
        "allowlistRuleCount": len(allowlist_rules),
        "observedAt": _utc_now(),
    }


def task_progress(
    *,
    root: Path,
    run_id: str | None = None,
    task_list: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Summarize task checklist progress from a task-list markdown file."""
    path_s = task_list or os.environ.get("SW_TASK_LIST", "")
    path = Path(path_s) if path_s else None
    if path and not path.is_absolute():
        path = root / path
    completed = remaining = 0
    rows: list[dict[str, Any]] = []
    if path and path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^-\s*\[([ xX])\]\s+(\d+\.\d+)\s+(.*)$", line.strip())
            if not m:
                continue
            done = m.group(1).lower() == "x"
            rows.append({"ref": m.group(2), "title": m.group(3).strip(), "done": done})
            if done:
                completed += 1
            else:
                remaining += 1
    return {
        "ok": True,
        "operation": "task_progress",
        "runId": run_id,
        "taskList": str(path) if path else None,
        "completed": completed,
        "remaining": remaining,
        "rows": rows,
        "observedAt": _utc_now(),
    }


def gap_capture(
    *,
    root: Path,
    title: str,
    detail: str = "",
    run_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Capture a gap item via planning gap-capture when available; else durable local write."""
    from handoff.bundle import atomic_write_json

    fallback_error = ""
    try:
        import planning_gap_capture as pgc  # type: ignore

        if hasattr(pgc, "put_gap_draft"):
            result = pgc.put_gap_draft(
                root,
                signal_id=f"mcp-{_utc_now().replace(':', '')}",
                title=title,
                payload={"detail": detail, "source": "mcp"},
            )
            return {"ok": True, "operation": "gap_capture", "result": result}
    except Exception as exc:
        fallback_error = str(exc)

    rel = Path(".shipwright") / "gaps" / f"mcp-{_utc_now().replace(':', '')}.json"
    payload = {
        "title": title,
        "detail": detail,
        "runId": run_id,
        "source": "mcp",
        "capturedAt": _utc_now(),
        "fallbackError": fallback_error or None,
    }
    atomic_write_json(root / rel, payload)
    return {"ok": True, "operation": "gap_capture", "path": str(rel), "result": payload}


def evidence_register(
    *,
    root: Path,
    path: str,
    kind: str = "artifact",
    run_id: str | None = None,
    **_: Any,
) -> dict[str, Any]:
    """Register an evidence artifact with digest under the run evidence store."""
    from handoff.bundle import atomic_write_json

    target = (root / path).resolve()
    if not str(target).startswith(str(root.resolve())):
        return {"ok": False, "operation": "evidence_register", "error": "path_escape"}
    if not target.is_file():
        return {"ok": False, "operation": "evidence_register", "error": "missing_file"}
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    record = {
        "path": path,
        "kind": kind,
        "digest": f"sha256:{digest}",
        "runId": run_id,
        "registeredAt": _utc_now(),
        "source": "mcp",
    }
    out_dir = root / ".shipwright" / "evidence"
    if run_id:
        out_dir = out_dir / run_id
    out_path = out_dir / f"{digest[:16]}.json"
    atomic_write_json(out_path, record)
    return {"ok": True, "operation": "evidence_register", "result": record, "path": str(out_path)}


def handoff_export(
    *,
    root: Path,
    destination: str,
    source_host: str,
    destination_host: str,
    run_id: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Export a cross-host handoff bundle via the shared handoff application API."""
    from handoff.bundle import (
        build_continuation_payload,
        export_cross_host_bundle,
        source_repo_id_for_remote,
    )
    from handoff.validate_bundle import digest_payload

    base_path = kwargs.get("base_bundle")
    if base_path:
        base = json.loads(Path(base_path).read_text(encoding="utf-8"))
    else:
        fixture = _REPO / "core" / "tests" / "fixtures" / "bundle_self_test" / "pass.json"
        base = json.loads(fixture.read_text(encoding="utf-8"))
        if kwargs.get("goal"):
            base["goal"] = kwargs["goal"]
        base.pop("bundleDigest", None)
        base["bundleDigest"] = digest_payload(base)

    remote = kwargs.get("remote_url") or ""
    head = kwargs.get("head") or ("0" * 40)
    continuation = build_continuation_payload(
        task_baseline={
            "unitId": kwargs.get("unit_id") or "unit",
            "canonicalVersion": kwargs.get("task_version") or "1",
        },
        prd_baseline={"frozenCanonicalVersion": kwargs.get("prd_version") or "1"},
        repo={"worktree": str(root), "head": head, **({"remoteUrl": remote} if remote else {})},
        current_workflow_node_id=kwargs.get("node_id") or "node",
        completed_task_rows=list(kwargs.get("completed_task_rows") or []),
        remaining_task_rows=list(kwargs.get("remaining_task_rows") or []),
        unresolved_decisions=list(kwargs.get("unresolved_decisions") or []),
        evidence_references=list(kwargs.get("evidence_references") or []),
        model_attempt_lineage=list(kwargs.get("model_attempt_lineage") or []),
    )
    out = Path(destination)
    if not out.is_absolute():
        out = root / out
    enriched = export_cross_host_bundle(
        base,
        out,
        source_host=source_host,
        destination_host=destination_host,
        continuation_payload=continuation,
        pending_captures=list(kwargs.get("pending_captures") or []),
        source_repo_id=source_repo_id_for_remote(remote) if remote else None,
        source_head=head,
        transition_id=kwargs.get("transition_id") or str(uuid.uuid4()),
        root=root,
    )
    return {
        "ok": True,
        "operation": "handoff_export",
        "path": str(out),
        "transitionId": enriched.get("transition_id"),
        "runId": run_id,
        "bundleDigest": enriched.get("bundleDigest"),
    }


OPERATION_HANDLERS: dict[str, Callable[..., dict[str, Any]]] = {
    "status": status,
    "context_retrieve": context_retrieve,
    "task_progress": task_progress,
    "gap_capture": gap_capture,
    "evidence_register": evidence_register,
    "handoff_export": handoff_export,
}


def dispatch(operation: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Dispatch a bounded operation; unknown ops return permission-denied before app logic (SC6)."""
    name = str(operation or "").strip()
    if name not in ALLOWED_OPERATIONS:
        return {
            "ok": False,
            "error": "permission_denied",
            "operation": name,
            "allowed": sorted(ALLOWED_OPERATIONS),
        }
    handler = OPERATION_HANDLERS[name]
    args = dict(params or {})
    root = Path(args.pop("root", Path.cwd()))
    return handler(root=root, **args)


# CLI-equivalent aliases — MCP and CLI must call the same functions (R40).
cli_status = status
cli_context_retrieve = context_retrieve
cli_task_progress = task_progress
cli_gap_capture = gap_capture
cli_evidence_register = evidence_register
cli_handoff_export = handoff_export
