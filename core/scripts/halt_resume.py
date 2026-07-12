#!/usr/bin/env python3
"""Standardized halt-resume schema + validator for legitimate deliver halts (PRD 065 R25)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

REQUIRED_FIELDS = ("resumeCommand", "haltCause", "autonomyDirective", "runId")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def resolve_autonomy_directive(root: Path) -> str:
    deliver = _load_workflow_config(root).get("deliver") or {}
    autonomy = deliver.get("autonomy") if isinstance(deliver, dict) else {}
    if not isinstance(autonomy, dict):
        return "autonomous"
    return str(autonomy.get("mode", "autonomous"))


def resolve_run_id(state: dict[str, Any] | None) -> str:
    if state:
        run_id = state.get("runId") or state.get("scopedRunId")
        if run_id:
            return str(run_id)
        branch = (state.get("target") or {}).get("branch") or ""
        slug = branch.split("/", 1)[1] if "/" in branch else branch or "unknown"
        from inflight_signal import run_id_from_slug

        return run_id_from_slug(slug)
    return "deliver-unknown"


def try_load_deliver_state(root: Path) -> dict[str, Any] | None:
    try:
        from wave_state import load_deliver_state, sync_canonical_state_read

        sync_canonical_state_read(root)
        return load_deliver_state(root)
    except Exception:
        return None


def validate_halt_resume(
    block: dict[str, Any],
    *,
    require_phase_slug: bool = False,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not isinstance(block, dict):
        return False, ["halt-resume:not-object"]
    for field in REQUIRED_FIELDS:
        value = block.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"halt-resume:missing-{field}")
    if require_phase_slug:
        phase_slug = block.get("phaseSlug")
        if not isinstance(phase_slug, str) or not phase_slug.strip():
            errors.append("halt-resume:missing-phaseSlug")
    return len(errors) == 0, errors


def build_halt_resume(
    root: Path,
    state: dict[str, Any] | None,
    *,
    halt_cause: str,
    phase_slug: str | None = None,
    resume_command: str | None = None,
) -> dict[str, Any]:
    from wave_failure import resume_deliver_command

    state = state or {}
    block: dict[str, Any] = {
        "resumeCommand": resume_command or resume_deliver_command(root, state),
        "haltCause": halt_cause,
        "autonomyDirective": resolve_autonomy_directive(root),
        "runId": resolve_run_id(state),
        "generatedAt": utc_now(),
    }
    if phase_slug:
        block["phaseSlug"] = phase_slug
    ok, errors = validate_halt_resume(block, require_phase_slug=bool(phase_slug))
    if not ok:
        block["validationErrors"] = errors
    return block


def enrich_legitimate_halt(
    payload: dict[str, Any],
    root: Path,
    state: dict[str, Any] | None,
    *,
    halt_cause: str,
    phase_slug: str | None = None,
    resume_command: str | None = None,
    persist_halt_count: bool = True,
) -> dict[str, Any]:
    block = build_halt_resume(
        root,
        state,
        halt_cause=halt_cause,
        phase_slug=phase_slug,
        resume_command=resume_command,
    )
    payload["haltResume"] = block
    if state is not None and persist_halt_count:
        state["legitimateHaltCount"] = int(state.get("legitimateHaltCount") or 0) + 1
    return payload


def enrich_fail_extra(
    root: Path,
    extra: dict[str, Any],
    *,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    halt_cause = str(extra.get("cause") or extra.get("halt") or "")
    if not halt_cause:
        return extra
    if state is None:
        state = try_load_deliver_state(root)
    phase_slug = extra.get("phaseSlug")
    if not isinstance(phase_slug, str) or not phase_slug.strip():
        phase_slug = None
    return enrich_legitimate_halt(
        extra,
        root,
        state,
        halt_cause=halt_cause,
        phase_slug=phase_slug,
        persist_halt_count=state is not None,
    )
