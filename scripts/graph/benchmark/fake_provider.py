#!/usr/bin/env python3
"""Deterministic fake model provider for benchmark CI lane (PRD 272 R18)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class FakeProviderError(RuntimeError):
    """Raised when fake-provider lane configuration is invalid."""


@dataclass(frozen=True)
class FakeModelResponse:
    """Deterministic provider output keyed by case pin and lane."""

    case_id: str
    lane: str
    pin_digest: str
    verdict: str
    head_sha: str
    verifier_class: str
    advisory: bool = False
    tokens_used: int = 0

    def to_trace_evidence(self) -> dict[str, Any]:
        return {
            "traceRefId": f"fake:{self.case_id}:{self.lane}",
            "headSha": self.head_sha,
            "verifierClass": self.verifier_class,
            "verdict": self.verdict,
            "advisory": self.advisory,
        }


class FakeModelProvider:
    """Hermetic provider that never calls external model APIs."""

    def __init__(self, *, lane: str, head_sha: str) -> None:
        if not lane:
            raise FakeProviderError("lane is required")
        if not head_sha:
            raise FakeProviderError("head_sha is required")
        self.lane = lane
        self.head_sha = head_sha

    def _seed(self, case_id: str, pin_digest: str) -> int:
        digest = hashlib.sha256(
            f"{self.lane}:{case_id}:{pin_digest}:{self.head_sha}".encode("utf-8")
        ).hexdigest()
        return int(digest[:8], 16)

    def invoke(
        self,
        *,
        case_id: str,
        pin_digest: str,
        required_verifier_class: str,
        candidate: bool,
    ) -> FakeModelResponse:
        seed = self._seed(case_id, pin_digest)
        lane_penalty = 1 if candidate and self.lane == "candidate" else 0
        passes = (seed % 5) > lane_penalty
        return FakeModelResponse(
            case_id=case_id,
            lane=self.lane,
            pin_digest=pin_digest,
            verdict="pass" if passes else "fail",
            head_sha=self.head_sha,
            verifier_class=required_verifier_class,
            advisory=False,
            tokens_used=32 + (seed % 128),
        )

    def invoke_json(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        response = self.invoke(
            case_id=str(payload["caseId"]),
            pin_digest=str(payload["pinDigest"]),
            required_verifier_class=str(payload.get("requiredVerifierClass") or "mechanical"),
            candidate=bool(payload.get("candidate")),
        )
        return {
            "response": response.to_trace_evidence(),
            "tokensUsed": response.tokens_used,
            "provider": "fake",
            "lane": self.lane,
            "deterministicSeed": self._seed(
                str(payload["caseId"]),
                str(payload["pinDigest"]),
            ),
        }


def run_fake_provider_lane(
    *,
    lane: str,
    head_sha: str,
    cases: tuple[Mapping[str, Any], ...],
    candidate: bool = False,
) -> list[dict[str, Any]]:
    provider = FakeModelProvider(lane=lane, head_sha=head_sha)
    return [
        provider.invoke_json(
            {
                "caseId": case["caseId"],
                "pinDigest": case["pinDigest"],
                "requiredVerifierClass": case.get("requiredVerifierClass") or "mechanical",
                "candidate": candidate,
            }
        )
        for case in cases
    ]


def lane_report(records: list[Mapping[str, Any]]) -> dict[str, Any]:
    passes = sum(
        1
        for record in records
        if (record.get("response") or {}).get("verdict") == "pass"
    )
    return {
        "recordCount": len(records),
        "passCount": passes,
        "passRate": passes / len(records) if records else 0.0,
        "provider": "fake",
        "payloadDigest": hashlib.sha256(
            json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
