#!/usr/bin/env python3
"""Terminal status integrity — provenance marker, validation, resolution (PRD 036 R13–R17)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess

from _sw import interpreter
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from check_gate_lib import validate_pr_test_plan_gate

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

VALID_STATUS_VERDICTS = frozenset({"merge-ready-green", "blocked"})
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GATE_SUBSET_KEYS = ("verdict", "coderabbitLanded", "head")
DEFAULT_REEMIT_MAX = 2
DEFAULT_TIP_QUIESCENCE_SECONDS = 60

DIFFERENTIATED_STALL_CAUSES = frozenset(
    {
        "orphan-worktree-adopt-pending",
        "merge-queue-wait",
        "external-ci-wait",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def gate_subset(gate: Any) -> Any:
    if gate is None:
        return None
    if not isinstance(gate, dict):
        return "__invalid__"
    return {k: gate[k] for k in sorted(GATE_SUBSET_KEYS) if k in gate}


def ship_steps_checksum(ship_steps: Any) -> str | None:
    if ship_steps is None:
        return None
    if not isinstance(ship_steps, dict):
        return None
    canonical = json.dumps(ship_steps, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def canonical_provenance_payload(status: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": status.get("verdict"),
        "phase": status.get("phase"),
        "head": status.get("head"),
        "gate": gate_subset(status.get("gate")),
        "shipStepsChecksum": ship_steps_checksum(status.get("shipSteps")),
    }


def compute_provenance_marker(status: dict[str, Any]) -> str:
    payload = canonical_provenance_payload(status)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def attach_provenance_marker(doc: dict[str, Any]) -> dict[str, Any]:
    doc = dict(doc)
    doc["provenanceMarker"] = compute_provenance_marker(doc)
    return doc


def validate_provenance_marker(status: dict[str, Any]) -> tuple[bool, str | None]:
    recorded = status.get("provenanceMarker")
    if not recorded or not isinstance(recorded, str):
        return False, "phase-status:missing-provenance"
    expected = compute_provenance_marker(status)
    if recorded != expected:
        return False, "phase-status:forged-provenance"
    return True, None


def is_full_head_sha(head: Any) -> bool:
    return isinstance(head, str) and bool(SHA_PATTERN.match(head))


def resolve_write_head(cwd: Path | None = None) -> str:
    """Resolve git HEAD for durable status writes (phase status.json and gap-check)."""
    root = cwd or Path.cwd()
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def validate_gate_json(gate: Any, root: Path | None = None) -> tuple[bool, str | None]:
    if gate is None:
        return True, None
    if not isinstance(gate, dict):
        return False, "phase-status:invalid-gate"
    try:
        json.loads(json.dumps(gate))
    except (TypeError, ValueError):
        return False, "phase-status:invalid-gate"
    pr_test_plan = gate.get("prTestPlan")
    if pr_test_plan is not None and root is not None:
        manifest_err = validate_pr_test_plan_gate(root, pr_test_plan)
        if manifest_err:
            return False, f"phase-status:prTestPlan-{manifest_err}"
    return True, None


def repo_root_for_path(path: Path) -> Path | None:
    proc = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return None


def validate_terminal_status_shape(
    status: dict[str, Any], root: Path | None = None
) -> tuple[bool, str | None]:
    verdict = status.get("verdict")
    if verdict not in VALID_STATUS_VERDICTS:
        return False, "phase-status:invalid-verdict"
    ok, cause = validate_provenance_marker(status)
    if not ok:
        return False, cause
    if verdict == "merge-ready-green" and not is_full_head_sha(status.get("head")):
        return False, "phase-status:abbreviated-head"
    ok_gate, gate_cause = validate_gate_json(status.get("gate"), root)
    if not ok_gate:
        return False, gate_cause
    return True, None
