"""Planning domain model — PlanningUnit records only (PRD 082 phase 11 / R27)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class PlanningUnit:
    id: str
    type: str
    status: str
    title: str
    visibility: str
    edges: str
    body_path: str
    opaque_title: bool = False
    edge_map: dict[str, Any] | None = None
    source: str = ""
    schedule: str = ""


@dataclass(frozen=True)
class StoreResult:
    verdict: str
    unit_id: str
    body_path: str
    backend: str
    content: str | None = None
    hash: str | None = None
    reason: str | None = None
    inert: bool = False
    notice: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "verdict": self.verdict,
            "unitId": self.unit_id,
            "bodyPath": self.body_path,
            "backend": self.backend,
        }
        if self.content is not None:
            out["content"] = self.content
        if self.hash is not None:
            out["hash"] = self.hash
        if self.reason is not None:
            out["reason"] = self.reason
        if self.inert:
            out["inert"] = True
        if self.notice:
            out["notice"] = self.notice
        return out


MATERIALIZE_MISSING_FROZEN_BODY = "materialize:missing-frozen-body"


def materialize_missing_result(unit_id: str, body_path: str, backend_id: str) -> StoreResult:
    """Typed fail-closed cause when a frozen body cannot be materialized (PRD 069 R5)."""
    return StoreResult("missing", unit_id, body_path, backend_id, reason=MATERIALIZE_MISSING_FROZEN_BODY)
