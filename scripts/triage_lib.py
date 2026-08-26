#!/usr/bin/env python3
"""Deterministic triage tier classification with monotonic merge (PRD 272 R25)."""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

TIER_QUICK = "quick"
TIER_STANDARD = "standard"
TIER_FULL = "full"
TIER_ORDER = {TIER_QUICK: 0, TIER_STANDARD: 1, TIER_FULL: 2}

RISK_TRIGGERS: dict[str, str] = {
    "auth": "security",
    "authn": "security",
    "authz": "security",
    "authentication": "security",
    "authorization": "security",
    "login": "security",
    "session": "security",
    "oauth": "security",
    "jwt": "security",
    "payment": "security",
    "payments": "security",
    "billing": "security",
    "pii": "security",
    "credentials": "security",
    "token": "security",
    "encryption": "security",
    "public api": "security",
    "public endpoint": "security",
    "external api": "security",
    "webhook": "security",
    "stripe": "billing-routing",
    "paddle": "billing-routing",
    "subscription": "billing-routing",
    "migration": "data-migration",
    "data migration": "data-migration",
    "schema migration": "data-migration",
    "backfill": "data-migration",
}

AMBIGUITY_MARKERS = (
    "maybe",
    "possibly",
    "not sure",
    "unclear",
    "tbd",
    "figure out",
    "explore",
    "investigate",
    "spike",
    "prototype",
)


@dataclass
class TierResult:
    tier: str
    base_tier: str
    floor_tier: str | None = None
    mechanical_tier: str | None = None
    advisory_tier: str | None = None
    veto_tier: str | None = None
    matched_risk_triggers: list[str] = field(default_factory=list)
    matched_ambiguity: list[str] = field(default_factory=list)
    override: str | None = None
    misroute_promoted: bool = False
    prior_tier: str | None = None
    reduction_path: str | None = None
    signals: list[str] = field(default_factory=list)
    explain: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tier": self.tier,
            "baseTier": self.base_tier,
            "floorTier": self.floor_tier,
            "mechanicalTier": self.mechanical_tier,
            "advisoryTier": self.advisory_tier,
            "vetoTier": self.veto_tier,
            "matchedRiskTriggers": list(self.matched_risk_triggers),
            "matchedAmbiguity": list(self.matched_ambiguity),
            "override": self.override,
            "misroutePromoted": self.misroute_promoted,
            "priorTier": self.prior_tier,
            "reductionPath": self.reduction_path,
            "signals": list(self.signals),
        }
        if self.explain is not None:
            payload["explain"] = self.explain
        return payload


def _normalize(text: str) -> str:
    return text.lower().strip()


def _tier_max(tiers: Sequence[str]) -> str:
    if not tiers:
        return TIER_STANDARD
    return max(tiers, key=lambda t: TIER_ORDER.get(t, 0))


def _bump_tier(tier: str) -> str:
    if tier == TIER_QUICK:
        return TIER_STANDARD
    if tier == TIER_STANDARD:
        return TIER_FULL
    return TIER_FULL


def base_tier_from_file_count(file_count: int | None) -> str:
    if file_count is None:
        return TIER_STANDARD
    if file_count <= 1:
        return TIER_QUICK
    if file_count <= 5:
        return TIER_STANDARD
    return TIER_FULL


def scan_risk_triggers(text: str) -> list[str]:
    normalized = _normalize(text)
    matches: list[str] = []
    for keyword in sorted(RISK_TRIGGERS.keys(), key=len, reverse=True):
        if keyword in normalized:
            matches.append(keyword)
    return matches


def scan_ambiguity_markers(text: str) -> list[str]:
    normalized = _normalize(text)
    return [marker for marker in AMBIGUITY_MARKERS if marker in normalized]


def classify_mechanical(
    *,
    description: str = "",
    file_paths: Sequence[str] = (),
    file_count: int | None = None,
    override_tier: str | None = None,
    prior_tier: str | None = None,
    re_score: bool = False,
) -> TierResult:
    """Mechanical tier from rubric — file count is not the sole Full trigger."""
    if override_tier:
        tier = _normalize(override_tier)
        if tier not in TIER_ORDER:
            raise ValueError(f"invalid override tier: {override_tier}")
        return TierResult(
            tier=tier,
            base_tier=tier,
            override=tier,
            signals=[f"override: {tier}"],
        )

    scope_text = " ".join([description, *file_paths])
    resolved_count = file_count
    if resolved_count is None and file_paths:
        resolved_count = len(file_paths)

    rename_only = bool(
        re.match(r"^rename\b", _normalize(description))
        or "rename only" in _normalize(description)
    )

    base = base_tier_from_file_count(resolved_count)
    if rename_only and resolved_count is not None and resolved_count >= 6:
        base = TIER_STANDARD
    risk_matches = scan_risk_triggers(scope_text)
    floor = TIER_STANDARD if risk_matches else None
    ambiguity_matches = scan_ambiguity_markers(scope_text)
    bumped = _bump_tier(base) if ambiguity_matches else base
    candidates = [bumped]
    if floor:
        candidates.append(floor)
    mechanical = _tier_max(candidates)

    misroute = False
    if re_score and prior_tier == TIER_QUICK and TIER_ORDER[mechanical] > TIER_ORDER[TIER_QUICK]:
        misroute = True

    signals = [f"file_count: {resolved_count} -> {base}"]
    if risk_matches:
        signals.append(f"risk_triggers: {risk_matches} -> floor Standard")
    if ambiguity_matches:
        signals.append(f"ambiguity: {ambiguity_matches} -> bumped")
    if misroute:
        signals.append("misroute_reentry: promoted from Quick")

    return TierResult(
        tier=mechanical,
        base_tier=base,
        floor_tier=floor,
        mechanical_tier=mechanical,
        matched_risk_triggers=risk_matches,
        matched_ambiguity=ambiguity_matches,
        misroute_promoted=misroute,
        prior_tier=prior_tier,
        signals=signals,
    )


def merge_tier_monotonic(
    mechanical: TierResult,
    advisory_tier: str | None = None,
    *,
    authorized_reduction_to: str | None = None,
    reduction_path: str | None = None,
) -> TierResult:
    """Union/max-rigor merge; reductions only via authorized R7 paths."""
    advisory = _normalize(advisory_tier or mechanical.tier)
    if advisory not in TIER_ORDER:
        advisory = mechanical.tier
    merged = _tier_max([mechanical.tier, advisory])
    if authorized_reduction_to:
        reduced = _normalize(authorized_reduction_to)
        if reduced not in TIER_ORDER:
            raise ValueError(f"invalid reduction tier: {authorized_reduction_to}")
        if TIER_ORDER[reduced] < TIER_ORDER[merged]:
            if not reduction_path:
                raise ValueError("tier reduction requires authorized reduction path (R7)")
            merged = reduced
    result = TierResult(
        tier=merged,
        base_tier=mechanical.base_tier,
        floor_tier=mechanical.floor_tier,
        mechanical_tier=mechanical.mechanical_tier or mechanical.tier,
        advisory_tier=advisory,
        matched_risk_triggers=list(mechanical.matched_risk_triggers),
        matched_ambiguity=list(mechanical.matched_ambiguity),
        override=mechanical.override,
        misroute_promoted=mechanical.misroute_promoted,
        prior_tier=mechanical.prior_tier,
        reduction_path=reduction_path,
        signals=list(mechanical.signals) + [f"merged: max(mechanical,{advisory}) -> {merged}"],
    )
    return result


ADVISORY_SCORE_QUICK_MAX = 0.34
ADVISORY_SCORE_STANDARD_MAX = 0.67
SAFETY_VETO_FULL_MAX = 0.0
SAFETY_VETO_STANDARD_MAX = 0.5


def advisory_tier_from_score(score: float | None) -> str | None:
    """Map a fresh advisory score to a triage tier; absent scores stay unset."""
    if score is None:
        return None
    value = float(score)
    if value >= ADVISORY_SCORE_STANDARD_MAX:
        return TIER_FULL
    if value >= ADVISORY_SCORE_QUICK_MAX:
        return TIER_STANDARD
    return TIER_QUICK


def safety_veto_tier_from_aggregation(aggregation: Mapping[str, Any]) -> str | None:
    """Fresh safety-floor evidence enforces a minimum tier before advisory promotion."""
    safety_score = aggregation.get("safetyFloorScore")
    if safety_score is None:
        return None
    value = float(safety_score)
    if value <= SAFETY_VETO_FULL_MAX:
        return TIER_FULL
    if value < SAFETY_VETO_STANDARD_MAX:
        return TIER_STANDARD
    return None


def evidence_aggregation(evidence: Mapping[str, Any]) -> dict[str, Any]:
    from triage_evidence import aggregate_weighted_advisory

    explain = evidence.get("explain")
    if isinstance(explain, Mapping):
        aggregation = explain.get("aggregation")
        if isinstance(aggregation, Mapping):
            return dict(aggregation)
    signals = evidence.get("signals")
    if isinstance(signals, list):
        return aggregate_weighted_advisory(signals)
    return {}


def _build_evidence_explain(
    evidence: Mapping[str, Any],
    aggregation: Mapping[str, Any],
) -> dict[str, Any]:
    explain = evidence.get("explain")
    payload = dict(explain) if isinstance(explain, Mapping) else {}
    payload["aggregation"] = dict(aggregation)
    payload["authority"] = "non-authoritative"
    payload["absent"] = list(aggregation.get("absent") or [])
    payload["excludedStale"] = list(aggregation.get("excludedStale") or [])
    return payload


def apply_veto_first_evidence(
    mechanical: TierResult,
    evidence: Mapping[str, Any] | None,
) -> TierResult:
    """Apply safety veto then advisory promotion; evidence explain is non-authoritative."""
    if evidence is None:
        return mechanical
    from triage_evidence import parse_triage_evidence

    parsed = parse_triage_evidence(evidence)
    aggregation = evidence_aggregation(parsed)
    explain = _build_evidence_explain(parsed, aggregation)
    veto_tier = safety_veto_tier_from_aggregation(aggregation)
    advisory_tier = advisory_tier_from_score(aggregation.get("advisoryScore"))

    vetoed = mechanical
    extra_signals: list[str] = []
    if veto_tier:
        vetoed = TierResult(
            tier=_tier_max([mechanical.tier, veto_tier]),
            base_tier=mechanical.base_tier,
            floor_tier=mechanical.floor_tier,
            mechanical_tier=mechanical.mechanical_tier or mechanical.tier,
            matched_risk_triggers=list(mechanical.matched_risk_triggers),
            matched_ambiguity=list(mechanical.matched_ambiguity),
            override=mechanical.override,
            misroute_promoted=mechanical.misroute_promoted,
            prior_tier=mechanical.prior_tier,
            signals=list(mechanical.signals) + [f"safety_veto: floor -> {veto_tier}"],
            veto_tier=veto_tier,
        )
        extra_signals.append(f"safety_veto: floor -> {veto_tier}")

    if mechanical.override:
        result = TierResult(
            tier=mechanical.tier,
            base_tier=mechanical.base_tier,
            floor_tier=mechanical.floor_tier,
            mechanical_tier=mechanical.mechanical_tier,
            advisory_tier=advisory_tier,
            veto_tier=veto_tier,
            matched_risk_triggers=list(mechanical.matched_risk_triggers),
            matched_ambiguity=list(mechanical.matched_ambiguity),
            override=mechanical.override,
            misroute_promoted=mechanical.misroute_promoted,
            prior_tier=mechanical.prior_tier,
            reduction_path=mechanical.reduction_path,
            signals=list(mechanical.signals) + extra_signals,
            explain=explain,
        )
        return result

    merged = merge_tier_monotonic(vetoed, advisory_tier)
    return TierResult(
        tier=merged.tier,
        base_tier=merged.base_tier,
        floor_tier=merged.floor_tier,
        mechanical_tier=merged.mechanical_tier,
        advisory_tier=advisory_tier,
        veto_tier=veto_tier,
        matched_risk_triggers=list(merged.matched_risk_triggers),
        matched_ambiguity=list(merged.matched_ambiguity),
        override=merged.override,
        misroute_promoted=merged.misroute_promoted,
        prior_tier=merged.prior_tier,
        reduction_path=merged.reduction_path,
        signals=list(merged.signals) + extra_signals,
        explain=explain,
    )


def classify_tier(
    *,
    description: str = "",
    file_paths: Sequence[str] = (),
    file_count: int | None = None,
    override_tier: str | None = None,
    advisory_tier: str | None = None,
    triage_evidence: Mapping[str, Any] | None = None,
    prior_tier: str | None = None,
    re_score: bool = False,
    authorized_reduction_to: str | None = None,
    reduction_path: str | None = None,
) -> TierResult:
    mechanical = classify_mechanical(
        description=description,
        file_paths=file_paths,
        file_count=file_count,
        override_tier=override_tier,
        prior_tier=prior_tier,
        re_score=re_score,
    )
    if triage_evidence is not None:
        return apply_veto_first_evidence(mechanical, triage_evidence)
    if mechanical.override:
        return mechanical
    return merge_tier_monotonic(
        mechanical,
        advisory_tier,
        authorized_reduction_to=authorized_reduction_to,
        reduction_path=reduction_path,
    )


def _cmd_classify(args: argparse.Namespace) -> int:
    result = classify_tier(
        description=args.description or "",
        file_count=args.file_count,
        override_tier=args.tier,
        advisory_tier=args.advisory_tier,
        prior_tier=args.prior_tier,
        re_score=args.re_score,
        authorized_reduction_to=args.reduction_to,
        reduction_path=args.reduction_path,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deterministic triage tier classifier")
    sub = parser.add_subparsers(dest="command", required=True)
    classify_parser = sub.add_parser("classify", help="Classify tier from mechanical + advisory signals")
    classify_parser.add_argument("--description", default="")
    classify_parser.add_argument("--file-count", type=int, dest="file_count")
    classify_parser.add_argument("--tier", dest="tier")
    classify_parser.add_argument("--advisory-tier", dest="advisory_tier")
    classify_parser.add_argument("--prior-tier", dest="prior_tier")
    classify_parser.add_argument("--re-score", action="store_true", dest="re_score")
    classify_parser.add_argument("--reduction-to", dest="reduction_to")
    classify_parser.add_argument("--reduction-path", dest="reduction_path")
    classify_parser.set_defaults(func=_cmd_classify)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
