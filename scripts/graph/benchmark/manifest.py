#!/usr/bin/env python3
"""Benchmark case manifest loader and validator (PRD 272 R17)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

MANIFEST_SCHEMA_VERSION = 1

REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "schemaVersion",
        "manifestId",
        "corpusVersion",
        "cases",
    }
)

REQUIRED_CASE_FIELDS = frozenset(
    {
        "caseId",
        "workflowType",
        "tier",
        "description",
        "seedPaths",
        "isolationMode",
        "cachePolicy",
        "pinDigest",
        "repetitions",
        "holdout",
        "provenance",
    }
)

WORKFLOW_TYPES = frozenset(
    {
        "bugfix",
        "api-change",
        "migration",
        "security",
        "refactor",
        "dependency-update",
        "flaky-test",
        "docs",
        "multi-component",
    }
)

CACHE_POLICIES = frozenset({"no-cache", "read-only", "content-addressed"})
ISOLATION_MODES = frozenset({"none", "process", "worktree", "container", "remote"})
PROVENANCE_VALUES = frozenset({"benchmark", "shadow", "replay"})


class BenchmarkManifestError(ValueError):
    """Raised when manifest structure or corpus coverage fails validation."""


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    workflow_type: str
    tier: str
    description: str
    seed_paths: tuple[str, ...]
    isolation_mode: str
    cache_policy: str
    pin_digest: str
    repetitions: int
    holdout: bool
    provenance: str
    required_verifier_class: str = "mechanical"

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkCase:
        missing = REQUIRED_CASE_FIELDS - set(raw.keys())
        if missing:
            raise BenchmarkManifestError(
                f"case missing required fields: {sorted(missing)}"
            )
        seed_paths = raw.get("seedPaths")
        if not isinstance(seed_paths, list) or not seed_paths:
            raise BenchmarkManifestError("seedPaths must be a non-empty list")
        repetitions = raw.get("repetitions")
        if isinstance(repetitions, bool) or not isinstance(repetitions, int) or repetitions < 1:
            raise BenchmarkManifestError("repetitions must be a positive integer")
        return cls(
            case_id=str(raw["caseId"]),
            workflow_type=str(raw["workflowType"]),
            tier=str(raw["tier"]),
            description=str(raw["description"]),
            seed_paths=tuple(str(path) for path in seed_paths),
            isolation_mode=str(raw["isolationMode"]),
            cache_policy=str(raw["cachePolicy"]),
            pin_digest=str(raw["pinDigest"]),
            repetitions=repetitions,
            holdout=bool(raw["holdout"]),
            provenance=str(raw["provenance"]),
            required_verifier_class=str(
                raw.get("requiredVerifierClass") or "mechanical"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "caseId": self.case_id,
            "workflowType": self.workflow_type,
            "tier": self.tier,
            "description": self.description,
            "seedPaths": list(self.seed_paths),
            "isolationMode": self.isolation_mode,
            "cachePolicy": self.cache_policy,
            "pinDigest": self.pin_digest,
            "repetitions": self.repetitions,
            "holdout": self.holdout,
            "provenance": self.provenance,
            "requiredVerifierClass": self.required_verifier_class,
        }


@dataclass(frozen=True)
class BenchmarkManifest:
    schema_version: int
    manifest_id: str
    corpus_version: str
    cases: tuple[BenchmarkCase, ...]

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> BenchmarkManifest:
        missing = REQUIRED_MANIFEST_FIELDS - set(raw.keys())
        if missing:
            raise BenchmarkManifestError(
                f"manifest missing required fields: {sorted(missing)}"
            )
        cases_raw = raw.get("cases")
        if not isinstance(cases_raw, list) or not cases_raw:
            raise BenchmarkManifestError("cases must be a non-empty list")
        cases = tuple(BenchmarkCase.from_dict(case) for case in cases_raw)
        return cls(
            schema_version=int(raw["schemaVersion"]),
            manifest_id=str(raw["manifestId"]),
            corpus_version=str(raw["corpusVersion"]),
            cases=cases,
        )

    def workflow_types_present(self) -> frozenset[str]:
        return frozenset(case.workflow_type for case in self.cases)

    def holdout_cases(self) -> tuple[BenchmarkCase, ...]:
        return tuple(case for case in self.cases if case.holdout)

    def eval_cases(self, *, include_holdout: bool = False) -> tuple[BenchmarkCase, ...]:
        if include_holdout:
            return self.cases
        return tuple(case for case in self.cases if not case.holdout)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "manifestId": self.manifest_id,
            "corpusVersion": self.corpus_version,
            "cases": [case.to_dict() for case in self.cases],
        }


def default_manifest_path(repo_root: str | Path) -> Path:
    return Path(repo_root) / ".sw" / "workflows" / "benchmark" / "case-manifest.json"


def load_manifest(path: str | Path) -> BenchmarkManifest:
    manifest_path = Path(path)
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise BenchmarkManifestError("manifest root must be an object")
    manifest = BenchmarkManifest.from_dict(raw)
    validate_manifest(manifest)
    return manifest


def validate_manifest(manifest: BenchmarkManifest) -> None:
    """Fail closed on schema drift, invalid enums, or incomplete MVP corpus (R17)."""
    if manifest.schema_version != MANIFEST_SCHEMA_VERSION:
        raise BenchmarkManifestError(
            f"unsupported schemaVersion {manifest.schema_version}"
        )
    present = manifest.workflow_types_present()
    missing_types = WORKFLOW_TYPES - present
    if missing_types:
        raise BenchmarkManifestError(
            f"corpus missing workflow types: {sorted(missing_types)}"
        )
    for case in manifest.cases:
        if case.workflow_type not in WORKFLOW_TYPES:
            raise BenchmarkManifestError(
                f"unknown workflowType {case.workflow_type!r} on {case.case_id}"
            )
        if case.isolation_mode not in ISOLATION_MODES:
            raise BenchmarkManifestError(
                f"invalid isolationMode on {case.case_id}: {case.isolation_mode}"
            )
        if case.cache_policy not in CACHE_POLICIES:
            raise BenchmarkManifestError(
                f"invalid cachePolicy on {case.case_id}: {case.cache_policy}"
            )
        if case.provenance not in PROVENANCE_VALUES:
            raise BenchmarkManifestError(
                f"invalid provenance on {case.case_id}: {case.provenance}"
            )
        if len(case.pin_digest) < 8:
            raise BenchmarkManifestError(
                f"pinDigest too short on {case.case_id}"
            )


def corpus_coverage_report(manifest: BenchmarkManifest) -> dict[str, Any]:
    present = manifest.workflow_types_present()
    return {
        "manifestId": manifest.manifest_id,
        "corpusVersion": manifest.corpus_version,
        "caseCount": len(manifest.cases),
        "workflowTypes": sorted(present),
        "holdoutCount": len(manifest.holdout_cases()),
        "complete": present >= WORKFLOW_TYPES,
    }
