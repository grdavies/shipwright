"""State-machine property extensions for resilience harness (PRD 323 R1–R6)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from unit_tests.resilience.harness import (
    InjectionBoundary,
    InjectionPlan,
    InjectionJournal,
    ResilienceHarness,
    TransitionRequest,
    TransitionResult,
    new_fixture_root,
)

PROPERTY_SUITE_MODULES: tuple[tuple[str, str, str], ...] = (
    ("R1", "generation-fence", "test_property_generation_fence.py"),
    ("R2", "cancel-fence", "test_property_cancel_fence.py"),
    ("R3", "cache-identity", "test_property_cache_identity.py"),
    ("R4", "finalize-checkpoint", "test_property_finalize_checkpoint.py"),
    ("R5", "assurance-monotonicity", "test_property_assurance.py"),
    ("R6", "merge-conflict", "test_property_merge_conflict.py"),
)


@dataclass(frozen=True)
class PropertyTransitionRequest(TransitionRequest):
    node_id: str = "node-1"
    assurance_after: int | None = None
    merge_conflict: bool = False
    explicit_resolution: dict[str, Any] | None = None


@dataclass
class PropertyFixtureState:
    cancelled_nodes: set[str] = field(default_factory=set)
    assurance_level: int = 0
    merge_conflict_open: bool = False
    merge_resolution: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None

    @property
    def meta_path(self) -> Path:
        raise RuntimeError("meta_path requires fixture root binding")

    def bind(self, root: Path) -> PropertyFixtureState:
        self._root = root  # noqa: SLF001 — test fixture binding
        return self

    def meta_file(self, root: Path) -> Path:
        return root / ".cursor" / "resilience-fixture" / "property-meta.json"

    def load(self, root: Path) -> dict[str, Any]:
        path = self.meta_file(root)
        if not path.is_file():
            return {
                "cancelledNodes": [],
                "assuranceLevel": 0,
                "mergeConflictOpen": False,
                "mergeResolution": None,
                "checkpoint": None,
            }
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}

    def save(self, root: Path, payload: dict[str, Any]) -> None:
        path = self.meta_file(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

    def sync(self, root: Path) -> None:
        payload = self.load(root)
        self.cancelled_nodes = set(str(item) for item in (payload.get("cancelledNodes") or []))
        self.assurance_level = int(payload.get("assuranceLevel") or 0)
        self.merge_conflict_open = bool(payload.get("mergeConflictOpen"))
        resolution = payload.get("mergeResolution")
        self.merge_resolution = resolution if isinstance(resolution, dict) else None
        checkpoint = payload.get("checkpoint")
        self.checkpoint = checkpoint if isinstance(checkpoint, dict) else None

    def persist(self, root: Path) -> None:
        self.save(
            root,
            {
                "cancelledNodes": sorted(self.cancelled_nodes),
                "assuranceLevel": self.assurance_level,
                "mergeConflictOpen": self.merge_conflict_open,
                "mergeResolution": self.merge_resolution,
                "checkpoint": self.checkpoint,
            },
        )


class PropertyHarness(ResilienceHarness):
    """Resilience harness with generation/cancel/cache/checkpoint property gates."""

    def __init__(
        self,
        root: Path,
        *,
        plan: InjectionPlan | None = None,
        journal: InjectionJournal | None = None,
    ) -> None:
        super().__init__(root, plan=plan, journal=journal)
        self.property = PropertyFixtureState()
        self.property.sync(root)

    def cancel_node(self, node_id: str) -> None:
        self.property.sync(self.root)
        self.property.cancelled_nodes.add(node_id)
        self.property.persist(self.root)

    def open_merge_conflict(self) -> None:
        self.property.sync(self.root)
        self.property.merge_conflict_open = True
        self.property.merge_resolution = None
        self.property.persist(self.root)

    def record_resolution(self, record: dict[str, Any]) -> None:
        self.property.sync(self.root)
        self.property.merge_resolution = dict(record)
        self.property.merge_conflict_open = False
        self.property.persist(self.root)

    def _write_checkpoint(self, request: PropertyTransitionRequest) -> None:
        self.property.sync(self.root)
        self.property.checkpoint = {
            "generation": request.generation,
            "cacheIdentity": request.cache_identity,
            "nodeId": request.node_id,
            "actor": request.actor,
            "assuranceLevel": self.property.assurance_level,
        }
        self.property.persist(self.root)

    def _resume_from_checkpoint(self) -> TransitionResult:
        self.property.sync(self.root)
        checkpoint = self.property.checkpoint
        if not isinstance(checkpoint, dict):
            return TransitionResult(
                verdict="blocked",
                boundary=InjectionBoundary.FINALIZE,
                cause="checkpoint-missing",
                journal=self.journal.to_dict(),
            )
        request = TransitionRequest(
            actor=str(checkpoint.get("actor") or "resume"),
            generation=int(checkpoint.get("generation") or 0),
            cache_identity=str(checkpoint.get("cacheIdentity") or ""),
        )
        clean = ResilienceHarness(self.root)
        result = clean.transition(request)
        if result.verdict == "pass":
            self.property.checkpoint = None
            self.property.persist(self.root)
        return TransitionResult(
            verdict=result.verdict,
            boundary=result.boundary,
            cause=result.cause,
            journal=self.journal.to_dict(),
        )

    def transition(self, request: TransitionRequest) -> TransitionResult:  # type: ignore[override]
        if not isinstance(request, PropertyTransitionRequest):
            request = PropertyTransitionRequest(
                actor=request.actor,
                generation=request.generation,
                cache_identity=request.cache_identity,
                run_id=request.run_id,
            )
        self.property.sync(self.root)

        if request.node_id in self.property.cancelled_nodes:
            return TransitionResult(
                verdict="blocked",
                boundary=InjectionBoundary.ADMISSION,
                cause="cancelled-node",
                journal=self.journal.to_dict(),
            )

        if request.merge_conflict and request.explicit_resolution is None:
            self.property.merge_conflict_open = True
            self.property.persist(self.root)
            return TransitionResult(
                verdict="blocked",
                boundary=InjectionBoundary.ADMISSION,
                cause="merge-conflict-unresolved",
                journal=self.journal.to_dict(),
            )

        if self.property.merge_conflict_open and request.explicit_resolution is None:
            return TransitionResult(
                verdict="blocked",
                boundary=InjectionBoundary.ADMISSION,
                cause="merge-conflict-unresolved",
                journal=self.journal.to_dict(),
            )

        if request.explicit_resolution is not None:
            self.record_resolution(request.explicit_resolution)

        if request.assurance_after is not None:
            if request.assurance_after < self.property.assurance_level:
                return TransitionResult(
                    verdict="blocked",
                    boundary=InjectionBoundary.CACHE,
                    cause="assurance-decrease-forbidden",
                    journal=self.journal.to_dict(),
                )
            self.property.assurance_level = request.assurance_after
            self.property.persist(self.root)

        self._write_checkpoint(request)
        result = super().transition(request)
        if result.verdict == "injected" and result.boundary == InjectionBoundary.FINALIZE:
            resumed = self._resume_from_checkpoint()
            if resumed is not None:
                return resumed
        return result


__all__ = [
    "PROPERTY_SUITE_MODULES",
    "PropertyFixtureState",
    "PropertyHarness",
    "PropertyTransitionRequest",
    "new_fixture_root",
]
