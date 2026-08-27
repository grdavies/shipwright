"""GitLab planning-store P2 spec stub (PRD 333 phase 7 / R7–R8, R13).

Non-shipping adapter — reports ``not-enabled`` and exposes conformance metadata only.
Cannot enter ``SHIPPED_BACKENDS`` until green corpus/conformance evidence.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ._common import log_operation
from ..model import StoreResult
from ..repository import PlanningStoreBackend

BACKEND_ID = "gitlab-planning-store"
SPEC_REL_PATH = "core/providers/planning-store/gitlab.md"
PROGRAM_PRIORITY_ID = "gitlab-planning-store"


def _conformance_constants() -> Any:
    from _planning_pkg_loader import load_submodule

    return load_submodule("provider_conformance")


def register_gitlab_planning_store_stub() -> dict[str, Any]:
    """Registration surface for ``planning_store_facade`` — metadata only, not enabled."""
    pc = _conformance_constants()
    matrix = pc.planning_store_capability_matrix()
    return {
        "backendId": BACKEND_ID,
        "status": "not-enabled",
        "shipped": False,
        "parityComplete": False,
        "specPath": SPEC_REL_PATH,
        "programPriorityId": PROGRAM_PRIORITY_ID,
        "matrixVersion": matrix["matrixVersion"],
        "mandatoryVerbs": list(pc.MANDATORY_PLANNING_STORE_VERBS),
        "corpusScenarios": sorted(pc.PLANNING_STORE_CORPUS_SCENARIOS),
        "normalizedErrors": sorted(pc.NORMALIZED_PLANNING_STORE_ERRORS),
        "declaredDegradations": [
            {"id": "gitlab-native-links-degraded", "verbs": ["put"]},
            {"id": "resync-on-stale-revision", "verbs": ["materialize"]},
        ],
    }


def gitlab_planning_store_parity_gate(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on parity claims for the P2 stub (R8, R11, R16)."""
    pc = _conformance_constants()
    base = pc.refuse_unsupported_parity_claim(claim)
    failures = list(base.get("failures") or [])
    backend = str(claim.get("backend") or "")
    if backend != BACKEND_ID:
        failures.append({"field": "backend", "error": "unexpected-backend", "observed": backend})
    if claim.get("parityComplete") is True:
        failures.append({"field": "parityComplete", "error": "p2-stub-parity-claim-refused"})
    if claim.get("enabled") is True or claim.get("status") == "enabled":
        failures.append({"field": "status", "error": "p2-stub-enablement-refused"})
    if claim.get("shipped") is True:
        failures.append({"field": "shipped", "error": "p2-stub-shipped-claim-refused"})
    return {
        "verdict": "ok" if not failures else "fail",
        "action": "gitlab-planning-store-parity-gate",
        "backend": BACKEND_ID,
        "failures": failures,
        "baseCheck": base,
    }


class GitlabPlanningStoreStubBackend(PlanningStoreBackend):
    """Present-but-inert GitLab planning-store adapter (P2 stub)."""

    backend_id = BACKEND_ID

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        super().__init__(root, cfg)

    def _not_enabled(self, unit_id: str, body_path: str, *, op: str) -> StoreResult:
        log_operation(op, unit_id, body_path, None, self.backend_id, notice="not-enabled")
        return StoreResult(
            "deferred",
            unit_id,
            body_path,
            self.backend_id,
            reason="not-enabled",
            inert=True,
            notice="gitlab-planning-store is a P2 spec stub — not shipped",
        )

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        return self._not_enabled(unit_id, body_path, op="put")

    def get(self, unit_id: str, body_path: str) -> StoreResult:
        return self._not_enabled(unit_id, body_path, op="get")

    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        return self._not_enabled(unit_id, body_path, op="exists")

    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        return self._not_enabled(unit_id, body_path, op="materialize")

    def freeze(self, unit_id: str, body_path: str) -> dict[str, Any]:
        result = self._not_enabled(unit_id, body_path, op="freeze")
        return {
            "verdict": "fail",
            "code": "not-enabled",
            "backend": self.backend_id,
            "unitId": unit_id,
            "bodyPath": body_path,
            "inert": result.inert,
            "notice": result.notice,
        }


def conformance_metadata_only() -> dict[str, Any]:
    """Alias for doctor/status surfaces that need stub metadata without enablement."""
    payload = register_gitlab_planning_store_stub()
    payload["action"] = "gitlab-planning-store-conformance-metadata"
    return payload
