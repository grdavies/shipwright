#!/usr/bin/env python3
"""Bounded reviewer selection helpers (PRD 326 R17–R18; PRD 351 R10–R14).

Prompt-lineage hash serialisation and attribution schema are documented in
``docs/guides/configuration.md`` under **Attribution and lineage hashes**.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence, TypedDict

from graph.reviewer_metrics.cost import enforce_cost_ceiling
from graph.reviewer_metrics.harvest import HarvestRecord, harvest_score_map
from graph.reviewer_metrics.independence import ReviewerAxisIdentity, score_independence
from graph.reviewer_metrics.ranking import SelectionFloorError, apply_bounded_selection
from host_lib import load_workflow_config

DEFAULT_MAX_PERSONAS = 32
DEFAULT_MIN_PERSONAS = 1
DEFAULT_COST_CEILING: float | None = None

UNRESOLVED_MODEL_IDS = frozenset({"inherit", "parent", "default", "auto", ""})

# Always strip these before lineage hashing (R13) — never hash raw secrets/prompts.
DEFAULT_LINEAGE_REDACTION_FIELDS = frozenset(
    {
        "raw_prompt",
        "prompt",
        "prompt_text",
        "api_key",
        "api_keys",
        "user_id",
        "user_token",
        "user_identifying_token",
    }
)


class UnresolvableIdentity(Exception):
    """Sentinel: model identity is inherit/unresolved at independence evaluation (R10)."""


class IndependenceResult(TypedDict):
    """Outcome of concrete author/reviewer identity comparison (R10–R11, R14)."""

    independent: bool
    author_model_identity: tuple[str, str, str]
    reviewer_model_identity: tuple[str, str, str]
    assertion_status: Literal["verified", "unverified"]


class IndependenceRecord(TypedDict):
    """Persisted independence assertion fields (R12–R14)."""

    author_model_identity: tuple[str, str, str]
    reviewer_model_identity: tuple[str, str, str]
    author_lineage_hash: str | None
    reviewer_lineage_hash: str | None
    external_finding_count: int
    assertion_status: Literal["verified", "unverified"]


__all__ = [
    "DEFAULT_COST_CEILING",
    "DEFAULT_LINEAGE_REDACTION_FIELDS",
    "DEFAULT_MAX_PERSONAS",
    "DEFAULT_MIN_PERSONAS",
    "IndependenceRecord",
    "IndependenceResult",
    "SelectionConfig",
    "UNRESOLVED_MODEL_IDS",
    "UnresolvableIdentity",
    "apply_bounded_code_review",
    "apply_bounded_doc_review",
    "assertion_meets_requirement",
    "build_independence_record",
    "compute_lineage_hash",
    "evaluate_independence",
    "load_harvest_record",
    "load_selection_config",
    "selection_bytes_unchanged",
]


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


def _is_unresolved_model_id(model_id: Any) -> bool:
    if model_id is None or not isinstance(model_id, str):
        return True
    text = model_id.strip()
    if text.lower() in UNRESOLVED_MODEL_IDS:
        return True
    return text.startswith("$") or text.startswith("{")


def _enforce_independence(
    selected: Sequence[str],
    *,
    model_id: str | None = None,
) -> list[str]:
    """Diversify correlated reviewers when a concrete model_id is available (R10).

    Unresolved placeholders (including the former ``inherit`` default) skip
    enforcement — they must not mint a false independence verdict.
    """
    if model_id is None or _is_unresolved_model_id(model_id):
        return list(selected)
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


def _identity_tuple(value: Any) -> tuple[str, str, str] | None:
    """Parse ``(provider, model_name, version)`` from tuple/list/mapping."""
    if isinstance(value, (tuple, list)) and len(value) == 3:
        provider, model_name, version = value
        if provider is None or model_name is None or version is None:
            return None
        provider_s, model_s, version_s = (
            str(provider).strip(),
            str(model_name).strip(),
            str(version).strip(),
        )
        if not provider_s or not model_s or not version_s:
            return None
        return (provider_s, model_s, version_s)
    if isinstance(value, Mapping):
        provider = value.get("provider")
        model_name = value.get("model_name", value.get("model"))
        version = value.get("version")
        if provider is None or model_name is None or version is None:
            return None
        provider_s, model_s, version_s = (
            str(provider).strip(),
            str(model_name).strip(),
            str(version).strip(),
        )
        if not provider_s or not model_s or not version_s:
            return None
        return (provider_s, model_s, version_s)
    return None


def evaluate_independence(record: dict[str, Any]) -> IndependenceResult:
    """Compare concrete author/reviewer identities; refuse inherit placeholders (R10–R11)."""
    model_id = record.get("model_id", record.get("reviewer_model_id"))
    if _is_unresolved_model_id(model_id):
        raise UnresolvableIdentity(
            f"model_id={model_id!r} is unresolved; independence verdict requires a concrete identity"
        )

    author = _identity_tuple(
        record.get("author_model_identity") or record.get("author_identity")
    )
    reviewer = _identity_tuple(
        record.get("reviewer_model_identity") or record.get("reviewer_identity")
    )

    if author is None or reviewer is None:
        placeholder = ("", "", "")
        return IndependenceResult(
            independent=False,
            author_model_identity=author or placeholder,
            reviewer_model_identity=reviewer or placeholder,
            assertion_status="unverified",
        )

    # Brand/tier labels alone are insufficient — tuple equality is the contract (R11).
    return IndependenceResult(
        independent=author != reviewer,
        author_model_identity=author,
        reviewer_model_identity=reviewer,
        assertion_status="verified",
    )


def assertion_meets_requirement(
    assertion_status: Literal["verified", "unverified"],
    required: Literal["verified", "unverified"],
) -> bool:
    """Return whether ``assertion_status`` satisfies ``required`` (R14)."""
    if required == "verified":
        return assertion_status == "verified"
    return assertion_status in ("verified", "unverified")


def compute_lineage_hash(context_repr: dict[str, Any], redaction_fields: list[str]) -> str:
    """SHA-256 over canonical JSON after redaction (R13 / TR4)."""
    excluded = {str(field) for field in redaction_fields} | set(DEFAULT_LINEAGE_REDACTION_FIELDS)
    filtered = {
        str(key): value
        for key, value in context_repr.items()
        if str(key) not in excluded
    }
    payload = json.dumps(filtered, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_independence_record(
    *,
    author_model_identity: tuple[str, str, str],
    reviewer_model_identity: tuple[str, str, str] | None,
    author_context: dict[str, Any] | None = None,
    reviewer_context: dict[str, Any] | None = None,
    redaction_fields: list[str] | None = None,
    external_finding_count: int = 0,
) -> IndependenceRecord:
    """Assemble an IndependenceRecord with lineage hashes (R12–R14)."""
    fields = list(redaction_fields or [])
    author_hash = (
        compute_lineage_hash(author_context, fields) if author_context is not None else None
    )
    if reviewer_model_identity is None:
        return IndependenceRecord(
            author_model_identity=author_model_identity,
            reviewer_model_identity=("", "", ""),
            author_lineage_hash=author_hash,
            reviewer_lineage_hash=None,
            external_finding_count=int(external_finding_count),
            assertion_status="unverified",
        )
    reviewer_hash = (
        compute_lineage_hash(reviewer_context, fields) if reviewer_context is not None else None
    )
    return IndependenceRecord(
        author_model_identity=author_model_identity,
        reviewer_model_identity=reviewer_model_identity,
        author_lineage_hash=author_hash,
        reviewer_lineage_hash=reviewer_hash,
        external_finding_count=int(external_finding_count),
        assertion_status="verified",
    )
