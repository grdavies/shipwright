"""Destination acknowledgement for cross-host HandoffBundle imports (PRD 349 R35)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .bundle import atomic_write_json

try:
    from shipwright_paths import destination_ack_path, runs_dir
except ImportError:  # pragma: no cover - script path bootstrap
    import sys

    _SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    from shipwright_paths import destination_ack_path, runs_dir


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_destination_ack(
    root: Path,
    *,
    run_id: str,
    transition_id: str,
    host_adapter_id: str,
    import_digest: str,
    agent_identity: str | None = None,
    imported_at: str | None = None,
) -> dict[str, Any]:
    """Atomically write destination_ack (TR5)."""
    record = {
        "hostAdapterId": str(host_adapter_id),
        "importedAt": imported_at or _utc_now(),
        "importDigest": str(import_digest),
        "transitionId": str(transition_id),
    }
    if agent_identity:
        record["agentIdentity"] = str(agent_identity)
    path = destination_ack_path(root, run_id, transition_id)
    atomic_write_json(path, record)
    return record


def read_destination_ack(root: Path, *, run_id: str, transition_id: str) -> dict[str, Any] | None:
    path = destination_ack_path(root, run_id, transition_id)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def list_pending_transitions(root: Path, *, run_id: str | None = None) -> list[dict[str, Any]]:
    """Bundles/transitions recorded without destination_ack appear as pending (R35)."""
    pending: list[dict[str, Any]] = []
    base = runs_dir(root)
    if not base.is_dir():
        return pending
    run_dirs = [base / run_id] if run_id else sorted(p for p in base.iterdir() if p.is_dir())
    for run_path in run_dirs:
        imports_dir = run_path / "imports"
        if not imports_dir.is_dir():
            continue
        acks_dir = run_path / "acks"
        for import_path in sorted(imports_dir.glob("*.json")):
            transition_id = import_path.stem
            ack_path = acks_dir / f"{transition_id}.json"
            if ack_path.is_file():
                continue
            try:
                payload = json.loads(import_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                payload = {}
            pending.append(
                {
                    "status": "pending",
                    "runId": run_path.name,
                    "transitionId": transition_id,
                    "source_host": payload.get("source_host"),
                    "destination_host": payload.get("destination_host"),
                    "importPath": str(import_path),
                }
            )
    return pending


def attach_ack_to_bundle(bundle: Mapping[str, Any], ack: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of bundle with destination_ack attached (excluded from digest)."""
    updated = dict(bundle)
    updated["destination_ack"] = dict(ack)
    return updated
