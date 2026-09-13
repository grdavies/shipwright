"""Neutral handoff readers — path resolution via shipwright_paths (PRD 349 R11–R14)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from shipwright_paths import (  # noqa: E402
    AllowlistMissingError,
    allowlist_path,
    deliver_runs_dir,
    gate_evidence_path,
    phase_evidence_path,
    require_allowlist_path,
)

__all__ = [
    "AllowlistMissingError",
    "allowlist_path",
    "deliver_runs_dir",
    "gate_evidence_path",
    "phase_evidence_path",
    "read_allowlist_rules",
    "read_deliver_status",
    "read_gate_evidence",
    "read_phase_evidence",
    "require_allowlist_path",
]


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def read_allowlist_rules(root: Path) -> list[str]:
    """Return allowlisted rule ids from the neutral/legacy allowlist file."""
    path = allowlist_path(root)
    payload = _read_json(path)
    if not payload:
        return []
    rules = payload.get("rules")
    if isinstance(rules, list):
        return [str(item) for item in rules if str(item).strip()]
    return []


def read_deliver_status(root: Path, run_id: str) -> dict[str, Any]:
    """Load deliver status.json for *run_id* from the resolved runs directory."""
    run_key = str(run_id).strip()
    if not run_key:
        return {}
    candidates = [
        deliver_runs_dir(root) / run_key / "status.json",
        gate_evidence_path(root, run_key).parent / "status.json",
    ]
    for candidate in candidates:
        payload = _read_json(candidate)
        if payload:
            return payload
    return {}


def read_gate_evidence(root: Path, run_id: str) -> list[dict[str, Any]]:
    """Load gate-evidence status records for *run_id*."""
    evidence_dir = gate_evidence_path(root, run_id)
    if not evidence_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.status.json")):
        payload = _read_json(path)
        if not payload:
            continue
        rows.append(
            {
                "kind": "gate-evidence",
                "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "verdict": str(payload.get("verdict") or ""),
                "gateId": str(payload.get("gateId") or path.stem.replace(".status", "")),
            }
        )
    return rows


def read_phase_evidence(root: Path, run_id: str, phase: str) -> list[dict[str, Any]]:
    """Load phase-evidence records for *run_id*/*phase*."""
    evidence_dir = phase_evidence_path(root, run_id, phase)
    if not evidence_dir.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(evidence_dir.glob("*.json")):
        payload = _read_json(path)
        if not payload:
            continue
        rows.append(
            {
                "kind": "phase-evidence",
                "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                "payload": payload,
            }
        )
    return rows
