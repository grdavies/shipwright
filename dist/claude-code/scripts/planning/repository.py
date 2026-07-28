"""Generic planning repository contract without provider leakage (PRD 082 phase 11 / R27)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from .model import StoreResult


class PlanningStoreBackend(ABC):
    """Backend-agnostic store contract — no labels, ETags, comments, or provider guards."""

    backend_id: str

    def __init__(self, root: Path, cfg: dict[str, Any]) -> None:
        self.root = root
        self.cfg = cfg

    def put(self, unit_id: str, body_path: str, content: str, *, content_class: str | None = None) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def get(self, unit_id: str, body_path: str) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def exists(self, unit_id: str, body_path: str) -> StoreResult:
        raise NotImplementedError

    @abstractmethod
    def materialize(self, unit_id: str, body_path: str, dest_path: Path) -> StoreResult:
        raise NotImplementedError

    def derive_unit_status(self, unit_id: str, body_path: str) -> str:
        """Map backend-native state to the unified four-state surface (+ unknown)."""
        result = self.get(unit_id, body_path)
        if result.verdict != "ok" or not result.content:
            return "unknown"
        from planning_canonical import infer_artifact_type

        artifact_type = infer_artifact_type(body_path)
        native = _native_status_from_content(result.content, artifact_type=artifact_type)
        return _unified_status_from_native(native, artifact_type)


def _native_status_from_content(content: str, *, artifact_type: str, state: str = "open", labels: list[str] | None = None) -> str:
    import planning_discover as pd

    class _Record:
        def __init__(self, body: str, lbls: list[str], st: str, unit_id: str, atype: str) -> None:
            self.body = body
            self.labels = lbls
            self.state = st
            self.unit_id = unit_id
            self.artifact_type = atype

    return pd._status_from_record(
        _Record(content, list(labels or []), state, "", artifact_type),
        content,
    )


def _unified_status_from_native(native_status: str, artifact_type: str) -> str:
    import planning_unit_status as pus

    return pus.map_native_status_to_unified(native_status, artifact_type)
