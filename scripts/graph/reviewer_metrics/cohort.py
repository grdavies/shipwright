#!/usr/bin/env python3
"""Cohort identity versioning for Elo ladder (PRD 273 R19)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

COHORT_SCHEMA_VERSION = 1


class CohortAction(str, Enum):
    COMPATIBLE = "compatible"
    PARTITION = "partition"
    MIGRATE = "migrate"


@dataclass(frozen=True)
class CohortIdentity:
    persona_version: str
    prompt_version: str
    model_version: str
    schema_version: int
    policy_version: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "personaVersion": self.persona_version,
            "promptVersion": self.prompt_version,
            "modelVersion": self.model_version,
            "schemaVersion": self.schema_version,
            "policyVersion": self.policy_version,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> CohortIdentity:
        return cls(
            persona_version=str(payload["personaVersion"]),
            prompt_version=str(payload["promptVersion"]),
            model_version=str(payload["modelVersion"]),
            schema_version=int(payload["schemaVersion"]),
            policy_version=str(payload["policyVersion"]),
        )

    def cohort_key(self) -> str:
        canonical = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def cohort_compatible(left: CohortIdentity, right: CohortIdentity) -> bool:
    return left.cohort_key() == right.cohort_key()


def partition_by_cohort(
    identities: Sequence[CohortIdentity],
) -> tuple[tuple[CohortIdentity, ...], ...]:
    buckets: dict[str, list[CohortIdentity]] = {}
    for identity in identities:
        buckets.setdefault(identity.cohort_key(), []).append(identity)
    return tuple(tuple(items) for items in buckets.values())


@dataclass(frozen=True)
class CohortResolution:
    action: CohortAction
    source: CohortIdentity
    target: CohortIdentity | None = None
    reason: str = ""


def resolve_cohort_transition(
    source: CohortIdentity,
    target: CohortIdentity,
) -> CohortResolution:
    if cohort_compatible(source, target):
        return CohortResolution(
            CohortAction.COMPATIBLE,
            source,
            target,
            "same cohort key",
        )
    if (
        source.schema_version != target.schema_version
        or source.policy_version != target.policy_version
    ):
        return CohortResolution(
            CohortAction.PARTITION,
            source,
            target,
            "incompatible schema/policy versions",
        )
    return CohortResolution(
        CohortAction.MIGRATE,
        source,
        target,
        "non-breaking persona/prompt/model revision",
    )
