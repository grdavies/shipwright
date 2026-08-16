#!/usr/bin/env python3
"""Detector registry and ecosystem coverage matrix (PRD 272 R1/R6)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

REGISTRY_REL = Path("core/sw-reference/capability-registry.json")

CAPABILITY_MIGRATION = "workflow.capability.migration-validation"
CAPABILITY_AUTH = "workflow.capability.security-auth-review"
CAPABILITY_API = "workflow.capability.api-compatibility"
CAPABILITY_SUPPLY_CHAIN = "workflow.capability.dependency-supply-chain"
CAPABILITY_STANDARD_REVIEW = "workflow.capability.standard-review"

DETECTOR_MIGRATION = "workflow.detector.migration"
DETECTOR_AUTH = "workflow.detector.auth"
DETECTOR_API = "workflow.detector.api"
DETECTOR_SUPPLY_CHAIN = "workflow.detector.supply-chain"


@dataclass(frozen=True)
class DetectorSpec:
    """Registered detector metadata."""

    id: str
    version: str
    capability_id: str
    intake_surfaces: tuple[str, ...]
    status: str = "shipped"


DEFAULT_DETECTORS: tuple[DetectorSpec, ...] = (
    DetectorSpec(
        id=DETECTOR_MIGRATION,
        version="1.0.0",
        capability_id=CAPABILITY_MIGRATION,
        intake_surfaces=(
            "db/migrations/**",
            "supabase/migrations/**",
            "alembic/**",
            "**/migrations/*.sql",
        ),
    ),
    DetectorSpec(
        id=DETECTOR_AUTH,
        version="1.0.0",
        capability_id=CAPABILITY_AUTH,
        intake_surfaces=(
            "**/auth/**",
            "**/middleware/**",
            "**/*credentials*",
            "**/*permission*",
            "**/*rbac*",
        ),
    ),
    DetectorSpec(
        id=DETECTOR_API,
        version="1.0.0",
        capability_id=CAPABILITY_API,
        intake_surfaces=(
            "**/openapi*.yaml",
            "**/openapi*.json",
            "**/routes/**",
            "**/api/**",
            "**/schema/**",
        ),
    ),
    DetectorSpec(
        id=DETECTOR_SUPPLY_CHAIN,
        version="1.0.0",
        capability_id=CAPABILITY_SUPPLY_CHAIN,
        intake_surfaces=(
            "package.json",
            "package-lock.json",
            "pnpm-lock.yaml",
            "yarn.lock",
            "Cargo.lock",
            "go.sum",
            "Pipfile.lock",
            "poetry.lock",
            "scripts/_sw/depmanifest.json",
            "scripts/_sw/vendor/**",
            ".sw/workflows/lock.json",
            ".github/workflows/**",
            ".gitmodules",
            "Dockerfile",
            "docker-compose*.yml",
        ),
    ),
)


def load_registry(root: Path) -> dict[str, Any]:
    path = root / REGISTRY_REL
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid capability registry: {path}")
    return payload


def detector_by_id(registry_payload: Mapping[str, Any] | None = None) -> dict[str, DetectorSpec]:
    """Resolve detector specs from registry payload or built-in defaults."""
    specs = list(DEFAULT_DETECTORS)
    if registry_payload:
        family = (registry_payload.get("families") or {}).get("workflow.detectors") or {}
        rows = family.get("rows") or []
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                detector_id = str(row.get("id") or "")
                if not detector_id:
                    continue
                specs.append(
                    DetectorSpec(
                        id=detector_id,
                        version=str(row.get("version") or "1.0.0"),
                        capability_id=str(row.get("capabilityId") or ""),
                        intake_surfaces=tuple(
                            str(item) for item in (row.get("intakeSurfaces") or ())
                        ),
                        status=str(row.get("status") or "shipped"),
                    )
                )
    by_id: dict[str, DetectorSpec] = {}
    for spec in specs:
        by_id[spec.id] = spec
    return by_id


def capability_verification_step(capability_id: str) -> str:
    """Map typed requiredCapabilityId to a concrete verification step."""
    mapping = {
        CAPABILITY_MIGRATION: "sw-verify-migration",
        CAPABILITY_AUTH: "sw-verify-auth",
        CAPABILITY_API: "sw-verify-api-compat",
        CAPABILITY_SUPPLY_CHAIN: "sw-verify-supply-chain",
        CAPABILITY_STANDARD_REVIEW: "sw-review-standard",
    }
    return mapping.get(capability_id, f"sw-verify-{capability_id.rsplit('.', 1)[-1]}")
