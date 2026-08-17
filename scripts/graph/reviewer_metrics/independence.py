#!/usr/bin/env python3
"""Independence scorer — flags correlated persona×model pairs (PRD 273 R5). Advisory only."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

ADVISORY_ONLY = True


class CorrelationKind(str, Enum):
    SHARED_MODEL = "shared-model"
    SHARED_PROMPT = "shared-prompt"
    IDENTICAL_CLUSTER = "identical-cluster"


@dataclass(frozen=True)
class ReviewerAxisIdentity:
    persona_id: str
    model_id: str
    prompt_template_id: str = ""
    cluster_id: str = ""


@dataclass(frozen=True)
class CorrelatedPairReport:
    persona_a: str
    model_a: str
    persona_b: str
    model_b: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class IndependenceReport:
    persona_model_keys: tuple[str, ...]
    correlated_pairs: tuple[CorrelatedPairReport, ...]
    advisory_only: bool = True


def persona_model_key(persona_id: str, model_id: str) -> str:
    return f"{persona_id}×{model_id}"


def _pair_sort_key(pair: CorrelatedPairReport) -> tuple[str, str, str, str]:
    left = (pair.persona_a, pair.model_a)
    right = (pair.persona_b, pair.model_b)
    if left > right:
        left, right = right, left
    return left[0], left[1], right[0], right[1]


def _merge_reasons(existing: tuple[str, ...], new_reason: str) -> tuple[str, ...]:
    ordered = list(existing)
    if new_reason not in ordered:
        ordered.append(new_reason)
    return tuple(sorted(ordered))


def _register_pair(
    pairs: dict[tuple[str, str], CorrelatedPairReport],
    left: ReviewerAxisIdentity,
    right: ReviewerAxisIdentity,
    reason: str,
) -> None:
    if left.persona_id == right.persona_id and left.model_id == right.model_id:
        return
    key_left = persona_model_key(left.persona_id, left.model_id)
    key_right = persona_model_key(right.persona_id, right.model_id)
    pair_key = tuple(sorted((key_left, key_right)))
    existing = pairs.get(pair_key)
    if existing is None:
        pairs[pair_key] = CorrelatedPairReport(
            persona_a=left.persona_id,
            model_a=left.model_id,
            persona_b=right.persona_id,
            model_b=right.model_id,
            reasons=(reason,),
        )
        return
    pairs[pair_key] = CorrelatedPairReport(
        persona_a=existing.persona_a,
        model_a=existing.model_a,
        persona_b=existing.persona_b,
        model_b=existing.model_b,
        reasons=_merge_reasons(existing.reasons, reason),
    )


def _flag_group_correlations(
    group: Sequence[ReviewerAxisIdentity],
    reason: str,
    pairs: dict[tuple[str, str], CorrelatedPairReport],
) -> None:
    if len(group) < 2:
        return
    for index, left in enumerate(group):
        for right in group[index + 1 :]:
            _register_pair(pairs, left, right, reason)


def score_independence(identities: Sequence[ReviewerAxisIdentity]) -> IndependenceReport:
    """Flag correlated persona×model pairs — report-only; never gates execution."""
    persona_model_keys = tuple(
        sorted({persona_model_key(item.persona_id, item.model_id) for item in identities})
    )
    pairs: dict[tuple[str, str], CorrelatedPairReport] = {}

    by_model: dict[str, list[ReviewerAxisIdentity]] = {}
    by_prompt: dict[str, list[ReviewerAxisIdentity]] = {}
    by_cluster: dict[str, list[ReviewerAxisIdentity]] = {}

    for identity in identities:
        if identity.model_id:
            by_model.setdefault(identity.model_id, []).append(identity)
        if identity.prompt_template_id:
            by_prompt.setdefault(identity.prompt_template_id, []).append(identity)
        if identity.cluster_id:
            by_cluster.setdefault(identity.cluster_id, []).append(identity)

    for group in by_model.values():
        _flag_group_correlations(group, CorrelationKind.SHARED_MODEL.value, pairs)
    for group in by_prompt.values():
        _flag_group_correlations(group, CorrelationKind.SHARED_PROMPT.value, pairs)
    for group in by_cluster.values():
        _flag_group_correlations(group, CorrelationKind.IDENTICAL_CLUSTER.value, pairs)

    correlated = tuple(sorted(pairs.values(), key=_pair_sort_key))
    return IndependenceReport(
        persona_model_keys=persona_model_keys,
        correlated_pairs=correlated,
        advisory_only=ADVISORY_ONLY,
    )


def independence_warnings(report: IndependenceReport) -> tuple[str, ...]:
    """Human-readable advisory warnings for export surfaces."""
    warnings: list[str] = []
    for pair in report.correlated_pairs:
        reasons = ",".join(pair.reasons)
        warnings.append(
            f"correlated:{pair.persona_a}×{pair.model_a}<->{pair.persona_b}×{pair.model_b}:{reasons}"
        )
    return tuple(warnings)
