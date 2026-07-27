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
from typing import Any

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
    root: Path | None = None,
) -> dict[str, Any]:
    current = normalize_tier(current_tier)
    proposed = normalize_tier(proposed_tier)
    direction = compare_tiers(current, proposed)
    receipt: dict[str, Any] = {
        "action": "final-triage-rescore",
        "currentTier": current,
        "proposedTier": proposed,
        "direction": direction,
        "timestamp": utc_now(),
        "signals": signals or {},
    }
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
    args = parser.parse_args(argv)
    signals = json.loads(args.signals) if args.signals else None
    out = evaluate_rescore(
        current_tier=args.current_tier,
        proposed_tier=args.proposed_tier,
        frozen=bool(args.frozen),
        justification=args.justification,
        actor=args.actor,
        unit_id=args.unit_id,
        signals=signals,
        root=Path(args.root).resolve(),
    )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("verdict") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
