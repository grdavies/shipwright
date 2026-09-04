#!/usr/bin/env python3
"""check-gate wiring helper for the packaged-install GA bar (PRD 342 R19).

check-gate evaluates GitHub check runs for the PR head. This helper documents
the job names published by ``.github/workflows/packaged-install.yml`` so local
preflight and check-gate consumers can treat them as first-class signals.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

PACKAGED_INSTALL_JOB_NAMES: tuple[str, ...] = (
    "packaged-install-cursor",
    "packaged-install-claude-code",
    "packaged-install-gate-wiring",
)

WORKFLOW_REL = Path(".github/workflows/packaged-install.yml")


def packaged_install_required_checks() -> list[str]:
    """Return GA bar check names that check-gate should observe."""
    return list(PACKAGED_INSTALL_JOB_NAMES)


def packaged_install_workflow_present(root: Path) -> bool:
    return (root / WORKFLOW_REL).is_file()


def annotate_check_gate_payload(payload: dict[str, Any], *, root: Path) -> dict[str, Any]:
    """Attach packaged-install GA metadata onto a check-gate payload."""
    annotated = dict(payload)
    annotated["packagedInstallGa"] = {
        "workflow": str(WORKFLOW_REL),
        "present": packaged_install_workflow_present(root),
        "requiredChecks": packaged_install_required_checks(),
    }
    return annotated
