#!/usr/bin/env python3
"""Paired benchmark eval runner with holdouts and R24 acceptance metrics (PRD 272 R18)."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from graph.benchmark.acceptance import TraceEvidence, evaluate_trace_acceptance
from graph.benchmark.fake_provider import FakeModelProvider, lane_report, run_fake_provider_lane as fake_lane_records
from graph.benchmark.manifest import BenchmarkCase, BenchmarkManifest, load_manifest


class BenchmarkRunnerError(RuntimeError):
    """Raised when benchmark execution preconditions fail."""


@dataclass(frozen=True)
class CaseRunResult:
    case_id: str
    lane: str
    repetition: int
    accepted: bool
    censored: bool
    cache_hit: bool
    isolation_mode: str
    cache_policy: str
    pin_digest: str
    evidence: TraceEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "caseId": self.case_id,
            "lane": self.lane,
            "repetition": self.repetition,
            "accepted": self.accepted,
            "censored": self.censored,
            "cacheHit": self.cache_hit,
            "isolationMode": self.isolation_mode,
            "cachePolicy": self.cache_policy,
            "pinDigest": self.pin_digest,
            "evidence": {
                "traceRefId": self.evidence.trace_ref_id,
                "headSha": self.evidence.head_sha,
                "verifierClass": self.evidence.verifier_class,
                "verdict": self.evidence.verdict,
                "advisory": self.evidence.advisory,
            },
        }


@dataclass
class BenchmarkMetrics:
    """Aggregate benchmark metrics with R24 acceptance predicate roll-up."""

    case_count: int = 0
    repetition_count: int = 0
    accepted_count: int = 0
    censored_count: int = 0
    cache_hits: int = 0
    acceptance_rate: float = 0.0
    r24_acceptance_predicate: bool = False
    holdout_evaluated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "caseCount": self.case_count,
            "repetitionCount": self.repetition_count,
            "acceptedCount": self.accepted_count,
            "censoredCount": self.censored_count,
            "cacheHits": self.cache_hits,
            "acceptanceRate": self.acceptance_rate,
            "r24AcceptancePredicate": self.r24_acceptance_predicate,
            "holdoutEvaluated": self.holdout_evaluated,
        }


@dataclass(frozen=True)
class PairedEvalReport:
    canonical_lane: str
    candidate_lane: str
    head_sha: str
    manifest_id: str
    eval_case_ids: tuple[str, ...]
    holdout_case_ids: tuple[str, ...]
    canonical_metrics: BenchmarkMetrics
    candidate_metrics: BenchmarkMetrics
    canonical_results: tuple[CaseRunResult, ...]
    candidate_results: tuple[CaseRunResult, ...]
    paired_delta_acceptance_rate: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonicalLane": self.canonical_lane,
            "candidateLane": self.candidate_lane,
            "headSha": self.head_sha,
            "manifestId": self.manifest_id,
            "evalCaseIds": list(self.eval_case_ids),
            "holdoutCaseIds": list(self.holdout_case_ids),
            "canonicalMetrics": self.canonical_metrics.to_dict(),
            "candidateMetrics": self.candidate_metrics.to_dict(),
            "pairedDeltaAcceptanceRate": self.paired_delta_acceptance_rate,
            "canonicalResults": [result.to_dict() for result in self.canonical_results],
            "candidateResults": [result.to_dict() for result in self.candidate_results],
        }


class _ResultCache:
    def __init__(self) -> None:
        self._store: dict[str, CaseRunResult] = {}

    def key(self, *, lane: str, case: BenchmarkCase, repetition: int) -> str:
        return f"{lane}:{case.case_id}:{repetition}:{case.pin_digest}"

    def get(self, key: str) -> CaseRunResult | None:
        return self._store.get(key)

    def put(self, key: str, value: CaseRunResult) -> None:
        self._store[key] = value


class PairedEvalRunner:
    """Runs canonical vs candidate lanes over a manifest with holdout isolation."""

    def __init__(
        self,
        manifest: BenchmarkManifest,
        *,
        head_sha: str,
        canonical_lane: str = "canonical",
        candidate_lane: str = "candidate",
    ) -> None:
        if not head_sha:
            raise BenchmarkRunnerError("head_sha is required")
        self.manifest = manifest
        self.head_sha = head_sha
        self.canonical_lane = canonical_lane
        self.candidate_lane = candidate_lane

    def _run_case_lane(
        self,
        *,
        case: BenchmarkCase,
        lane: str,
        provider: FakeModelProvider,
        cache: _ResultCache,
        candidate: bool,
    ) -> list[CaseRunResult]:
        results: list[CaseRunResult] = []
        for repetition in range(1, case.repetitions + 1):
            cache_key = cache.key(lane=lane, case=case, repetition=repetition)
            cache_hit = False
            if case.cache_policy == "content-addressed":
                cached = cache.get(cache_key)
                if cached is not None:
                    results.append(
                        CaseRunResult(
                            case_id=cached.case_id,
                            lane=cached.lane,
                            repetition=cached.repetition,
                            accepted=cached.accepted,
                            censored=cached.censored,
                            cache_hit=True,
                            isolation_mode=cached.isolation_mode,
                            cache_policy=cached.cache_policy,
                            pin_digest=cached.pin_digest,
                            evidence=cached.evidence,
                        )
                    )
                    continue
            elif case.cache_policy == "no-cache":
                cache_hit = False
            elif case.cache_policy == "read-only" and cache.get(cache_key) is not None:
                cached = cache.get(cache_key)
                assert cached is not None
                results.append(
                    CaseRunResult(
                        case_id=cached.case_id,
                        lane=cached.lane,
                        repetition=cached.repetition,
                        accepted=cached.accepted,
                        censored=cached.censored,
                        cache_hit=True,
                        isolation_mode=cached.isolation_mode,
                        cache_policy=cached.cache_policy,
                        pin_digest=cached.pin_digest,
                        evidence=cached.evidence,
                    )
                )
                continue

            response = provider.invoke(
                case_id=case.case_id,
                pin_digest=case.pin_digest,
                required_verifier_class=case.required_verifier_class,
                candidate=candidate,
            )
            evidence = TraceEvidence.from_dict(response.to_trace_evidence())
            accepted = evaluate_trace_acceptance(
                evidence,
                current_head_sha=self.head_sha,
                required_verifier_class=case.required_verifier_class,
            )
            censored = response.verdict != "pass" and not accepted
            result = CaseRunResult(
                case_id=case.case_id,
                lane=lane,
                repetition=repetition,
                accepted=accepted,
                censored=censored,
                cache_hit=cache_hit,
                isolation_mode=case.isolation_mode,
                cache_policy=case.cache_policy,
                pin_digest=case.pin_digest,
                evidence=evidence,
            )
            if case.cache_policy in {"content-addressed", "read-only"}:
                cache.put(cache_key, result)
            results.append(result)
        return results

    def _aggregate(self, results: tuple[CaseRunResult, ...], *, holdout: bool) -> BenchmarkMetrics:
        uncensored = tuple(result for result in results if not result.censored)
        accepted = tuple(result for result in uncensored if result.accepted)
        case_ids = frozenset(result.case_id for result in results)
        metrics = BenchmarkMetrics(
            case_count=len(case_ids),
            repetition_count=len(results),
            accepted_count=len(accepted),
            censored_count=len(results) - len(uncensored),
            cache_hits=sum(1 for result in results if result.cache_hit),
            acceptance_rate=(len(accepted) / len(uncensored)) if uncensored else 0.0,
            r24_acceptance_predicate=bool(uncensored) and all(result.accepted for result in uncensored),
            holdout_evaluated=holdout,
        )
        return metrics

    def run(self, *, include_holdout: bool = False) -> PairedEvalReport:
        eval_cases = self.manifest.eval_cases(include_holdout=include_holdout)
        holdout_ids = tuple(case.case_id for case in self.manifest.holdout_cases())
        eval_ids = tuple(case.case_id for case in eval_cases)
        canonical_provider = FakeModelProvider(lane=self.canonical_lane, head_sha=self.head_sha)
        candidate_provider = FakeModelProvider(lane=self.candidate_lane, head_sha=self.head_sha)
        canonical_cache = _ResultCache()
        candidate_cache = _ResultCache()
        canonical_results: list[CaseRunResult] = []
        candidate_results: list[CaseRunResult] = []
        for case in eval_cases:
            canonical_results.extend(
                self._run_case_lane(
                    case=case,
                    lane=self.canonical_lane,
                    provider=canonical_provider,
                    cache=canonical_cache,
                    candidate=False,
                )
            )
            candidate_results.extend(
                self._run_case_lane(
                    case=case,
                    lane=self.candidate_lane,
                    provider=candidate_provider,
                    cache=candidate_cache,
                    candidate=True,
                )
            )
        canonical_tuple = tuple(canonical_results)
        candidate_tuple = tuple(candidate_results)
        canonical_metrics = self._aggregate(canonical_tuple, holdout=include_holdout and bool(holdout_ids))
        candidate_metrics = self._aggregate(candidate_tuple, holdout=include_holdout and bool(holdout_ids))
        return PairedEvalReport(
            canonical_lane=self.canonical_lane,
            candidate_lane=self.candidate_lane,
            head_sha=self.head_sha,
            manifest_id=self.manifest.manifest_id,
            eval_case_ids=eval_ids,
            holdout_case_ids=holdout_ids,
            canonical_metrics=canonical_metrics,
            candidate_metrics=candidate_metrics,
            canonical_results=canonical_tuple,
            candidate_results=candidate_tuple,
            paired_delta_acceptance_rate=(
                candidate_metrics.acceptance_rate - canonical_metrics.acceptance_rate
            ),
        )


def run_paired_eval(
    manifest_path: str | Path,
    *,
    head_sha: str,
    include_holdout: bool = False,
) -> PairedEvalReport:
    manifest = load_manifest(manifest_path)
    runner = PairedEvalRunner(manifest, head_sha=head_sha)
    return runner.run(include_holdout=include_holdout)


def run_fake_provider_lane(
    manifest_path: str | Path,
    *,
    lane: str,
    head_sha: str,
    include_holdout: bool = False,
    candidate: bool = False,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    cases = manifest.eval_cases(include_holdout=include_holdout)
    records = lane_report(
        fake_lane_records(
            lane=lane,
            head_sha=head_sha,
            cases=tuple(case.to_dict() for case in cases),
            candidate=candidate,
        )
    )
    records["lane"] = lane
    records["manifestId"] = manifest.manifest_id
    records["holdoutExcluded"] = not include_holdout and bool(manifest.holdout_cases())
    return records
