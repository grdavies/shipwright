#!/usr/bin/env python3
"""Path-space coverage reporting (PRD 272 R5/R6)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from graph.detectors.patterns import classify_path
from graph.detectors.registry import DetectorSpec


@dataclass(frozen=True)
class CoverageReport:
    """Reportable detector path-space coverage for blind-spot visibility."""

    changed_paths: tuple[str, ...]
    classified_paths: tuple[str, ...]
    blind_spot_paths: tuple[str, ...]
    detector_hits: dict[str, tuple[str, ...]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changedPathCount": len(self.changed_paths),
            "classifiedPathCount": len(self.classified_paths),
            "blindSpotCount": len(self.blind_spot_paths),
            "blindSpotPaths": list(self.blind_spot_paths),
            "detectorHits": {
                detector_id: list(paths) for detector_id, paths in self.detector_hits.items()
            },
        }


def build_coverage_report(
    changed_paths: tuple[str, ...],
    detector_specs: tuple[DetectorSpec, ...],
) -> CoverageReport:
    hits: dict[str, list[str]] = {spec.id: [] for spec in detector_specs}
    classified: list[str] = []
    for path in changed_paths:
        matched_any = False
        for spec in detector_specs:
            if classify_path(path, spec.intake_surfaces):
                hits[spec.id].append(path)
                matched_any = True
        if matched_any:
            classified.append(path)
    blind_spots = tuple(path for path in changed_paths if path not in classified)
    return CoverageReport(
        changed_paths=changed_paths,
        classified_paths=tuple(classified),
        blind_spot_paths=blind_spots,
        detector_hits={key: tuple(value) for key, value in hits.items()},
    )
