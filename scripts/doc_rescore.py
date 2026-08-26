#!/usr/bin/env python3
"""Final triage rescore policy (PRD 081 R17).

Escalation is automatic and recorded. Downgrades require explicit human-attributed
justification. A rescore signal after freeze is recorded as amendment input and does
not reopen the frozen unit.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_transition_receipt import hash_json

TRIAGE_TIERS: tuple[str, ...] = ("Quick", "Standard", "Full")
TIER_RANK = {tier: index for index, tier in enumerate(TRIAGE_TIERS)}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_tier(raw: str | None) -> str:
    value = str(raw or "Standard").strip()
    lowered = value.lower()
    for tier in TRIAGE_TIERS:
        if tier.lower() == lowered:
            return tier
    return "Standard"


def tier_rank(tier: str) -> int:
    return TIER_RANK.get(normalize_tier(tier), TIER_RANK["Standard"])


def tier_from_triage_lib(raw: str) -> str:
    """Map triage_lib lowercase tiers to doc-loop title-case tiers."""
    normalized = str(raw or "").strip().lower()
    mapping = {"quick": "Quick", "standard": "Standard", "full": "Full"}
    return mapping.get(normalized, "Standard")


def _reject_veto_override_fields(signals: Mapping[str, Any] | None) -> str | None:
    if not isinstance(signals, Mapping):
        return None
    blocked = (
        "vetoOverride",
        "overrideSafetyVeto",
        "bypassSafetyKernel",
        "safetyKernelOverride",
    )
    for key in blocked:
        if key in signals:
            return f"veto-override-forbidden:{key}"
    return None


def _evidence_summary(evidence: Mapping[str, Any]) -> dict[str, Any]:
    from triage_evidence import parse_triage_evidence
    from triage_lib import advisory_tier_from_score, evidence_aggregation, safety_veto_tier_from_aggregation

    parsed = parse_triage_evidence(evidence)
    aggregation = evidence_aggregation(parsed)
    advisory = advisory_tier_from_score(aggregation.get("advisoryScore"))
    veto = safety_veto_tier_from_aggregation(aggregation)
    return {
        "version": parsed.get("version"),
        "aggregation": aggregation,
        "advisoryTier": tier_from_triage_lib(advisory) if advisory else None,
        "vetoTier": tier_from_triage_lib(veto) if veto else None,
        "absent": list(aggregation.get("absent") or []),
        "excludedStale": list(aggregation.get("excludedStale") or []),
        "authority": "non-authoritative",
    }


def apply_evidence_to_proposed_tier(
    proposed_tier: str,
    *,
    triage_evidence: Mapping[str, Any],
) -> dict[str, Any]:
    """Veto-first merge of evidence onto a proposed tier — no bypass surface (R3, R14, D6)."""
    summary = _evidence_summary(triage_evidence)
    veto_tier = summary.get("vetoTier")
    advisory_tier = summary.get("advisoryTier")
    candidates = [normalize_tier(proposed_tier)]
    if veto_tier:
        candidates.append(tier_from_triage_lib(str(veto_tier)))
    if advisory_tier:
        candidates.append(tier_from_triage_lib(str(advisory_tier)))
    effective = max(candidates, key=tier_rank)
    return {
        "effectiveTier": effective,
        "proposedTier": normalize_tier(proposed_tier),
        "vetoTier": tier_from_triage_lib(str(veto_tier)) if veto_tier else None,
        "advisoryTier": tier_from_triage_lib(str(advisory_tier)) if advisory_tier else None,
        "evidence": summary,
    }


def compare_tiers(current: str, proposed: str) -> str:
    cur = tier_rank(current)
    nxt = tier_rank(proposed)
    if nxt > cur:
        return "escalate"
    if nxt < cur:
        return "downgrade"
    return "unchanged"


def amendment_input_path(root: Path, unit_id: str) -> Path:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in unit_id)
    return root / ".cursor" / "sw-doc-runs" / "amendment-inputs" / f"{safe}.json"


def record_amendment_input(
    root: Path,
    *,
    unit_id: str,
    signal: dict[str, Any],
) -> dict[str, Any]:
    path = amendment_input_path(root, unit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload.get("signals"), list):
            existing = payload["signals"]
    entry = {
        "recordedAt": utc_now(),
        "signal": signal,
        "digest": hash_json(signal),
    }
    existing.append(entry)
    path.write_text(
        json.dumps(
            {
                "unitId": unit_id,
                "frozenUnitClosed": True,
                "signals": existing,
                "updatedAt": utc_now(),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "verdict": "pass",
        "action": "record-amendment-input",
        "unitId": unit_id,
        "path": str(path),
        "digest": entry["digest"],
    }


def evaluate_rescore(
    *,
    current_tier: str,
    proposed_tier: str,
    frozen: bool = False,
    justification: str | None = None,
    actor: str | None = None,
    unit_id: str | None = None,
    signals: dict[str, Any] | None = None,
    triage_evidence: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    override_error = _reject_veto_override_fields(signals)
    if override_error:
        return {
            "verdict": "fail",
            "error": override_error,
            "halt": "doc-loop:veto-override-forbidden",
            "appliedTier": normalize_tier(current_tier),
            "tier": normalize_tier(current_tier),
        }

    current = normalize_tier(current_tier)
    proposed = normalize_tier(proposed_tier)
    evidence_block: dict[str, Any] | None = None
    if triage_evidence is not None:
        try:
            evidence_block = apply_evidence_to_proposed_tier(
                proposed,
                triage_evidence=triage_evidence,
            )
        except Exception as exc:  # noqa: BLE001 — surface contract failures
            return {
                "verdict": "fail",
                "error": f"evidence-contract:{exc}",
                "halt": "doc-loop:evidence-invalid",
                "appliedTier": current,
                "tier": current,
            }
        proposed = str(evidence_block["effectiveTier"])

    direction = compare_tiers(current, proposed)
    receipt: dict[str, Any] = {
        "action": "final-triage-rescore",
        "currentTier": current,
        "proposedTier": proposed,
        "direction": direction,
        "timestamp": utc_now(),
        "signals": signals or {},
    }
    if evidence_block is not None:
        receipt["evidence"] = evidence_block["evidence"]
    if unit_id:
        receipt["unitId"] = unit_id

    if frozen:
        signal = {
            "currentTier": current,
            "proposedTier": proposed,
            "direction": direction,
            "signals": signals or {},
            "frozen": True,
        }
        amendment = None
        if root is not None and unit_id:
            amendment = record_amendment_input(root, unit_id=unit_id, signal=signal)
        return {
            "verdict": "pass",
            "action": "post-freeze-amendment-input",
            "appliedTier": current,
            "frozenUnitClosed": True,
            "receipt": receipt,
            "amendment": amendment,
        }

    if direction == "escalate":
        receipt["automatic"] = True
        receipt["appliedTier"] = proposed
        return {
            "verdict": "pass",
            "action": "rescore-escalate",
            "appliedTier": proposed,
            "tier": proposed,
            "receipt": receipt,
            "requiresBrainstorm": proposed == "Full" and current != "Full",
        }

    if direction == "downgrade":
        justification_text = (justification or "").strip()
        actor_text = (actor or "").strip()
        if not justification_text or not actor_text:
            receipt["halt"] = "downgrade-without-justification"
            return {
                "verdict": "fail",
                "error": "downgrade-without-justification",
                "halt": "doc-loop:rescore-downgrade",
                "appliedTier": current,
                "tier": current,
                "receipt": receipt,
            }
        receipt["justification"] = justification_text
        receipt["actor"] = actor_text
        receipt["appliedTier"] = proposed
        return {
            "verdict": "pass",
            "action": "rescore-downgrade",
            "appliedTier": proposed,
            "tier": proposed,
            "receipt": receipt,
        }

    receipt["appliedTier"] = current
    return {
        "verdict": "pass",
        "action": "rescore-unchanged",
        "appliedTier": current,
        "tier": current,
        "receipt": receipt,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Final triage rescore policy (PRD 081 R17).")
    parser.add_argument("--current-tier", required=True)
    parser.add_argument("--proposed-tier", required=True)
    parser.add_argument("--frozen", action="store_true")
    parser.add_argument("--justification")
    parser.add_argument("--actor")
    parser.add_argument("--unit-id")
    parser.add_argument("--root", default=".")
    parser.add_argument("--signals")
    parser.add_argument("--triage-evidence", dest="triage_evidence")
    args = parser.parse_args(argv)
    signals = json.loads(args.signals) if args.signals else None
    triage_evidence = json.loads(args.triage_evidence) if args.triage_evidence else None
    out = evaluate_rescore(
        current_tier=args.current_tier,
        proposed_tier=args.proposed_tier,
        frozen=bool(args.frozen),
        justification=args.justification,
        actor=args.actor,
        unit_id=args.unit_id,
        signals=signals,
        triage_evidence=triage_evidence,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("verdict") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
