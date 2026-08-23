#!/usr/bin/env python3
"""Bounded reviewer selection helpers (PRD 326 R17–R18)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from graph.reviewer_metrics.cost import enforce_cost_ceiling
from graph.reviewer_metrics.harvest import HarvestRecord, harvest_score_map
from graph.reviewer_metrics.independence import ReviewerAxisIdentity, score_independence
from graph.reviewer_metrics.ranking import SelectionFloorError, apply_bounded_selection
from host_lib import load_workflow_config

DEFAULT_MAX_PERSONAS = 32
DEFAULT_MIN_PERSONAS = 1
DEFAULT_COST_CEILING: float | None = None


@dataclass(frozen=True)
class SelectionConfig:
    max_personas: int
    min_personas: int
    cost_ceiling: float | None


def load_selection_config(cfg: Mapping[str, Any] | None) -> SelectionConfig:
    review = cfg.get("review") if isinstance(cfg, Mapping) else None
    selection = review.get("selection") if isinstance(review, Mapping) else None
    if not isinstance(selection, Mapping):
        return SelectionConfig(
            max_personas=DEFAULT_MAX_PERSONAS,
            min_personas=DEFAULT_MIN_PERSONAS,
            cost_ceiling=DEFAULT_COST_CEILING,
        )
    ceiling = selection.get("costCeiling")
    return SelectionConfig(
        max_personas=int(selection.get("maxPersonas", DEFAULT_MAX_PERSONAS)),
        min_personas=int(selection.get("minPersonas", DEFAULT_MIN_PERSONAS)),
        cost_ceiling=float(ceiling) if ceiling is not None else None,
    )


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def load_harvest_record(repo_root: Path) -> HarvestRecord | None:
    from graph.reviewer_metrics.store_adapter import ReviewerMetricsStoreAdapter

    adapter = ReviewerMetricsStoreAdapter(repo_root, may_egress=False)
    return adapter.load_latest_harvest()


def _rank_candidates(
    candidates: Sequence[str],
    harvest: HarvestRecord,
) -> list[str]:
    scores = harvest_score_map(harvest)
    return sorted(
        candidates,
        key=lambda reviewer_id: (
            -scores[reviewer_id].rating if reviewer_id in scores else 0.0,
            scores[reviewer_id].calibration_error
            if reviewer_id in scores and scores[reviewer_id].calibration_error is not None
            else 0.0,
            -(scores[reviewer_id].surviving_count if reviewer_id in scores else 0),
            reviewer_id,
        ),
    )


def _enforce_independence(
    selected: Sequence[str],
    *,
    model_id: str = "inherit",
) -> list[str]:
    if len(selected) < 2:
        return list(selected)
    identities = tuple(
        ReviewerAxisIdentity(persona_id=reviewer_id, model_id=model_id)
        for reviewer_id in selected
    )
    report = score_independence(identities)
    if not report.correlated_pairs:
        return list(selected)
    correlated: set[str] = set()
    for pair in report.correlated_pairs:
        correlated.add(pair.persona_a)
        correlated.add(pair.persona_b)
    if len(correlated) < len(selected):
        return list(selected)
    diversified = list(selected)
    for reviewer_id in reversed(diversified):
        trial = [item for item in diversified if item != reviewer_id]
        trial_report = score_independence(
            tuple(
                ReviewerAxisIdentity(persona_id=item, model_id=model_id) for item in trial
            )
        )
        if not trial_report.correlated_pairs or len(trial_report.correlated_pairs) < len(
            report.correlated_pairs
        ):
            diversified = trial
            report = trial_report
            if not report.correlated_pairs:
                break
    return diversified


def _bounded_ids(
    candidates: Sequence[str],
    harvest: HarvestRecord,
    selection: SelectionConfig,
    *,
    enforce_independence: bool,
) -> list[str]:
    ranked = _rank_candidates(candidates, harvest)
    bounded = apply_bounded_selection(
        ranked,
        max_personas=selection.max_personas,
        min_personas=selection.min_personas,
    )
    if bounded.verdict == "fail":
        raise SelectionFloorError(bounded.reason or "selection-floor")
    selected = list(bounded.selected)
    if enforce_independence:
        selected = _enforce_independence(selected)
    cost_map = {reviewer_id: 1.0 for reviewer_id in selected}
    cost_result = enforce_cost_ceiling(
        selected,
        cost_per_reviewer=cost_map,
        ceiling=selection.cost_ceiling,
        min_personas=selection.min_personas,
    )
    if cost_result.verdict == "fail":
        raise SelectionFloorError(cost_result.reason or "selection-floor")
    return list(cost_result.selected)


def apply_bounded_doc_review(
    base: dict[str, Any],
    *,
    repo_root: Path,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    harvest = load_harvest_record(repo_root)
    if harvest is None or not harvest.reviewers:
        return base
    panel = list(base.get("panel") or [])
    if not panel:
        return base
    selection = load_selection_config(cfg if cfg is not None else load_workflow_config(repo_root))
    try:
        selected = _bounded_ids(panel, harvest, selection, enforce_independence=False)
    except SelectionFloorError:
        return base
    if selected == panel:
        return base
    updated = dict(base)
    updated["panel"] = selected
    activation = dict(updated.get("activation") or {})
    activation["harvestBounded"] = True
    updated["activation"] = activation
    return updated


def apply_bounded_code_review(
    base: dict[str, Any],
    *,
    repo_root: Path,
    cfg: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    harvest = load_harvest_record(repo_root)
    if harvest is None or not harvest.reviewers:
        return base
    specialists = list(base.get("specialists") or [])
    if not specialists:
        return base
    selection = load_selection_config(cfg if cfg is not None else load_workflow_config(repo_root))
    try:
        selected = _bounded_ids(
            specialists,
            harvest,
            selection,
            enforce_independence=True,
        )
    except SelectionFloorError:
        return base
    if selected == specialists:
        return base
    updated = dict(base)
    updated["specialists"] = selected
    return updated


def selection_bytes_unchanged(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    return _canonical_bytes(before) == _canonical_bytes(after)
