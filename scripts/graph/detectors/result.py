#!/usr/bin/env python3
"""Versioned DetectorResult schema (PRD 272 R6)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

DETECTOR_RESULT_SCHEMA_VERSION = 1


class DetectorParseError(ValueError):
    """Recognized detector payload that cannot be parsed — fail closed."""


@dataclass(frozen=True)
class EvidenceRef:
    """A single evidence path with content hash."""

    path: str
    sha256: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "sha256": self.sha256}


@dataclass(frozen=True)
class DetectorResult:
    """Versioned detector output over declared scope plus base→worktree diff."""

    detector_id: str
    detector_version: str
    evidence: tuple[EvidenceRef, ...]
    confidence: str
    required_capability_ids: tuple[str, ...]
    disposition: str
    rule_id: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": DETECTOR_RESULT_SCHEMA_VERSION,
            "detectorId": self.detector_id,
            "detectorVersion": self.detector_version,
            "evidence": [item.to_dict() for item in self.evidence],
            "confidence": self.confidence,
            "requiredCapabilityIds": list(self.required_capability_ids),
            "disposition": self.disposition,
            "ruleId": self.rule_id,
            "detail": self.detail,
        }


def hash_path_content(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_detector_result(payload: Mapping[str, Any]) -> DetectorResult:
    """Parse and validate a DetectorResult; fail closed on recognized-but-unparseable input."""
    if not isinstance(payload, Mapping):
        raise DetectorParseError("detector result must be an object")
    version = payload.get("schemaVersion")
    if version is not None and version != DETECTOR_RESULT_SCHEMA_VERSION:
        raise DetectorParseError(f"unsupported detector result schema version: {version}")
    detector_id = payload.get("detectorId")
    detector_version = payload.get("detectorVersion")
    if not isinstance(detector_id, str) or not detector_id.strip():
        raise DetectorParseError("detectorId is required")
    if not isinstance(detector_version, str) or not detector_version.strip():
        raise DetectorParseError("detectorVersion is required")
    confidence = str(payload.get("confidence") or "unknown")
    disposition = str(payload.get("disposition") or "unknown")
    raw_caps = payload.get("requiredCapabilityIds")
    if raw_caps is None:
        caps: tuple[str, ...] = ()
    elif not isinstance(raw_caps, list):
        raise DetectorParseError("requiredCapabilityIds must be a list")
    else:
        caps = tuple(str(item) for item in raw_caps)
    evidence_items: list[EvidenceRef] = []
    raw_evidence = payload.get("evidence")
    if raw_evidence is not None:
        if not isinstance(raw_evidence, list):
            raise DetectorParseError("evidence must be a list")
        for item in raw_evidence:
            if not isinstance(item, Mapping):
                raise DetectorParseError("evidence entries must be objects")
            path = item.get("path")
            sha = item.get("sha256")
            if not isinstance(path, str) or not isinstance(sha, str):
                raise DetectorParseError("evidence path and sha256 are required")
            evidence_items.append(EvidenceRef(path=path, sha256=sha))
    return DetectorResult(
        detector_id=detector_id,
        detector_version=detector_version,
        evidence=tuple(evidence_items),
        confidence=confidence,
        required_capability_ids=caps,
        disposition=disposition,
        rule_id=str(payload.get("ruleId") or ""),
        detail=str(payload.get("detail") or ""),
    )


def union_required_capability_ids(
    results: tuple[DetectorResult, ...],
) -> tuple[str, ...]:
    """Monotonic union of required capability ids with stable ordering."""
    seen: dict[str, None] = {}
    for result in results:
        for cap_id in result.required_capability_ids:
            seen.setdefault(cap_id, None)
    return tuple(seen.keys())


def serialize_results(results: tuple[DetectorResult, ...]) -> str:
    return json.dumps([result.to_dict() for result in results], sort_keys=True)
