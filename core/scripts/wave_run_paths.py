#!/usr/bin/env python3
"""Run-id minting and run-scoped path accessors (PRD 081 R18, R20)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

GLOBAL_PLAN_REL = ".cursor/sw-deliver-plan.json"
RUNS_DIR_REL = ".cursor/sw-deliver-runs"
INDEX_FILENAME = "index.json"
STATE_FILENAME = "state.json"
PLAN_FILENAME = "plan.json"
EVENTS_FILENAME = "events.jsonl"
LEASE_FILENAME = "lease.json"
BLOCKER_FILENAME = "blocker.json"
TERMINAL_ACCEPTANCE_FILENAME = "terminal-acceptance.json"
PHASES_DIRNAME = "phases"

SAFE_RUN_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


class RunIdRequiredError(ValueError):
    """Raised when a run id is missing for a run-scoped accessor."""


class PhaseIdRequiredError(ValueError):
    """Raised when a stable phase id is missing."""


def require_run_id(run_id: str | None) -> str:
    if run_id is None or not str(run_id).strip():
        raise RunIdRequiredError("run id required")
    rid = str(run_id).strip()
    if not SAFE_RUN_ID_RE.match(rid):
        raise RunIdRequiredError(f"invalid run id: {run_id!r}")
    return rid


def require_phase_id(phase_id: str | None) -> str:
    if phase_id is None or not str(phase_id).strip():
        raise PhaseIdRequiredError("phase id required")
    return str(phase_id).strip()


def runs_root(root: Path) -> Path:
    return (root / RUNS_DIR_REL).resolve()


def run_directory(root: Path, run_id: str | None) -> Path:
    rid = require_run_id(run_id)
    return runs_root(root) / rid


def mint_run_id(root: Path) -> str:
    """Mint an immutable run identity at run creation (collision-checked)."""
    for _ in range(64):
        candidate = f"deliver-{uuid.uuid4().hex}"
        if not run_directory(root, candidate).exists():
            return candidate
    raise RuntimeError("failed to mint unique run id")


def plan_path(root: Path, run_id: str | None) -> Path:
    require_run_id(run_id)
    return run_directory(root, run_id) / PLAN_FILENAME


def state_path(root: Path, run_id: str | None) -> Path:
    require_run_id(run_id)
    return run_directory(root, run_id) / STATE_FILENAME


def events_path(root: Path, run_id: str | None) -> Path:
    require_run_id(run_id)
    return run_directory(root, run_id) / EVENTS_FILENAME


def lease_path(root: Path, run_id: str | None) -> Path:
    require_run_id(run_id)
    return run_directory(root, run_id) / LEASE_FILENAME


def blocker_path(root: Path, run_id: str | None) -> Path:
    require_run_id(run_id)
    return run_directory(root, run_id) / BLOCKER_FILENAME


def terminal_acceptance_path(root: Path, run_id: str | None) -> Path:
    require_run_id(run_id)
    return run_directory(root, run_id) / TERMINAL_ACCEPTANCE_FILENAME


def phase_directory(root: Path, run_id: str | None, phase_id: str | None) -> Path:
    pid = require_phase_id(phase_id)
    return run_directory(root, run_id) / PHASES_DIRNAME / pid


def phase_status_path(root: Path, run_id: str | None, phase_id: str | None) -> Path:
    return phase_directory(root, run_id, phase_id) / "status.json"


def phase_blocker_path(root: Path, run_id: str | None, phase_id: str | None) -> Path:
    return phase_directory(root, run_id, phase_id) / BLOCKER_FILENAME


def runs_index_path(root: Path) -> Path:
    return runs_root(root) / INDEX_FILENAME


INDEX_DISCOVERY_FIELDS = frozenset(
    {
        "runId",
        "target",
        "taskList",
        "verdict",
        "statePath",
        "updatedAt",
        "createdAt",
        "lockKeyDigest",
    }
)


def sanitize_index_entry(entry: dict[str, object]) -> dict[str, object]:
    """Keep only discovery fields on the root runs index (R20)."""
    return {key: value for key, value in entry.items() if key in INDEX_DISCOVERY_FIELDS}
