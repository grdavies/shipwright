#!/usr/bin/env python3
"""Memory envelope sensitivity tiers and monotonic declassification (PRD 082 R29).

Sensitivity tiers are ordered from least to most restrictive: public < internal < private < secret.
Missing or unparseable values resolve to the strictest tier. Raising restriction is always permitted;
lowering (declassification) requires an explicit human-gated approval journaled via
`/sw-memory-audit` — the sole operator path for lowering sensitivity.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from memory_envelope_v2 import SENSITIVITIES

Sensitivity = Literal["public", "internal", "private", "secret"]

SENSITIVITY_TIERS: tuple[str, ...] = ("public", "internal", "private", "secret")
STRICTEST_TIER: str = "secret"
HUMAN_GATE_COMMAND = "sw-memory-audit"

DECLASSIFICATION_JOURNAL_DIR = Path(".cursor") / "sw-memory-declassification-journal"
DECLASSIFICATION_JOURNAL_SCHEMA_VERSION = 1

TIER_RANK: dict[str, int] = {tier: index for index, tier in enumerate(SENSITIVITY_TIERS)}


class SensitivityError(ValueError):
    """Sensitivity tier resolution or transition failure."""


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tier_rank(tier: str) -> int:
    if tier not in TIER_RANK:
        raise SensitivityError(f"tier:unknown:{tier}")
    return TIER_RANK[tier]


def resolve_sensitivity(value: Any, *, default_to_strictest: bool = True) -> str:
    """Resolve a raw sensitivity value; missing/unparseable defaults to the strictest tier."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return STRICTEST_TIER if default_to_strictest else "internal"
    if not isinstance(value, str):
        return STRICTEST_TIER if default_to_strictest else "internal"
    normalized = value.strip().lower()
    if normalized in SENSITIVITIES:
        return normalized
    return STRICTEST_TIER if default_to_strictest else "internal"


def migrate_v1_sensitivity(value: Any) -> str:
    """Upgrade v1 records with missing or invalid sensitivity to the strictest tier."""
    return resolve_sensitivity(value, default_to_strictest=True)


def is_more_restrictive(from_tier: str, to_tier: str) -> bool:
    """True when ``to_tier`` is stricter than ``from_tier`` (raising restriction)."""
    return tier_rank(to_tier) > tier_rank(from_tier)


def is_less_restrictive(from_tier: str, to_tier: str) -> bool:
    """True when ``to_tier`` is less strict than ``from_tier`` (declassification)."""
    return tier_rank(to_tier) < tier_rank(from_tier)


def effective_tier(record_tier: Any, destination_policy_tier: Any) -> str:
    """Combine record sensitivity with a destination policy — never relaxes the destination."""
    record = resolve_sensitivity(record_tier)
    destination = resolve_sensitivity(destination_policy_tier)
    if tier_rank(record) >= tier_rank(destination):
        return record
    return destination


def propose_sensitivity_change(current: Any, new: Any) -> dict[str, Any]:
    """Classify a sensitivity transition without applying it."""
    from_tier = resolve_sensitivity(current)
    to_tier = resolve_sensitivity(new)
    if from_tier == to_tier:
        return {
            "verdict": "pass",
            "action": "no-change",
            "fromTier": from_tier,
            "toTier": to_tier,
            "requiresApproval": False,
        }
    if is_more_restrictive(from_tier, to_tier):
        return {
            "verdict": "pass",
            "action": "raise",
            "fromTier": from_tier,
            "toTier": to_tier,
            "requiresApproval": False,
        }
    if is_less_restrictive(from_tier, to_tier):
        return {
            "verdict": "pass",
            "action": "declassify",
            "fromTier": from_tier,
            "toTier": to_tier,
            "requiresApproval": True,
            "humanGate": HUMAN_GATE_COMMAND,
        }
    return {
        "verdict": "fail",
        "action": "invalid-transition",
        "fromTier": from_tier,
        "toTier": to_tier,
        "requiresApproval": False,
    }


def _journal_path(root: Path, scope: str = "default") -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (scope or "default").strip()) or "default"
    return root / DECLASSIFICATION_JOURNAL_DIR / f"{safe}.json"


def empty_declassification_journal(*, scope: str = "default") -> dict[str, Any]:
    return {
        "schemaVersion": DECLASSIFICATION_JOURNAL_SCHEMA_VERSION,
        "scope": scope,
        "entries": [],
        "updatedAt": utc_now_iso(),
    }


def load_declassification_journal(root: Path, *, scope: str = "default") -> dict[str, Any]:
    path = _journal_path(root, scope)
    if not path.is_file():
        return empty_declassification_journal(scope=scope)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_declassification_journal(scope=scope)
    if not isinstance(doc, dict):
        return empty_declassification_journal(scope=scope)
    doc.setdefault("schemaVersion", DECLASSIFICATION_JOURNAL_SCHEMA_VERSION)
    doc.setdefault("scope", scope)
    doc.setdefault("entries", [])
    return doc


def save_declassification_journal(root: Path, journal: dict[str, Any], *, scope: str = "default") -> Path:
    path = _journal_path(root, scope)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(journal)
    payload["scope"] = scope
    payload["updatedAt"] = utc_now_iso()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _entry_digest(entry: dict[str, Any]) -> str:
    body = {k: v for k, v in entry.items() if k != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def record_declassification_approval(
    root: Path,
    *,
    stable_id: str,
    from_tier: str,
    to_tier: str,
    approver: str,
    audit_command: str = HUMAN_GATE_COMMAND,
    scope: str = "default",
    reason: str | None = None,
) -> dict[str, Any]:
    """Journal a human-gated declassification approval (sole lowering path)."""
    src = stable_id.strip()
    approver_id = approver.strip()
    if not src:
        raise SensitivityError("approval:missing-stable-id")
    if not approver_id:
        raise SensitivityError("approval:missing-approver")
    resolved_from = resolve_sensitivity(from_tier)
    resolved_to = resolve_sensitivity(to_tier)
    if not is_less_restrictive(resolved_from, resolved_to):
        raise SensitivityError("approval:not-declassification")

    journal = load_declassification_journal(root, scope=scope)
    entry: dict[str, Any] = {
        "stableId": src,
        "fromTier": resolved_from,
        "toTier": resolved_to,
        "approver": approver_id,
        "auditCommand": audit_command,
        "approvedAt": utc_now_iso(),
    }
    if reason:
        entry["reason"] = reason
    entry["digest"] = _entry_digest(entry)
    entries = list(journal.get("entries") or [])
    entries.append(entry)
    journal["entries"] = entries
    path = save_declassification_journal(root, journal, scope=scope)
    return {"verdict": "pass", "journalPath": str(path), "entry": entry}


def _validate_approval(approval: dict[str, Any] | None, proposal: dict[str, Any]) -> dict[str, Any]:
    if not proposal.get("requiresApproval"):
        return {"verdict": "pass", "approved": False}
    if not isinstance(approval, dict):
        return {
            "verdict": "fail",
            "cause": "declassification:approval-required",
            "humanGate": HUMAN_GATE_COMMAND,
        }
    stable_id = str(approval.get("stableId") or "").strip()
    approver = str(approval.get("approver") or "").strip()
    from_tier = approval.get("fromTier") or proposal.get("fromTier")
    to_tier = approval.get("toTier") or proposal.get("toTier")
    if not stable_id or not approver:
        return {
            "verdict": "fail",
            "cause": "declassification:approval-incomplete",
            "humanGate": HUMAN_GATE_COMMAND,
        }
    if resolve_sensitivity(from_tier) != proposal.get("fromTier"):
        return {"verdict": "fail", "cause": "declassification:approval-from-mismatch"}
    if resolve_sensitivity(to_tier) != proposal.get("toTier"):
        return {"verdict": "fail", "cause": "declassification:approval-to-mismatch"}
    return {
        "verdict": "pass",
        "approved": True,
        "stableId": stable_id,
        "approver": approver,
        "fromTier": proposal.get("fromTier"),
        "toTier": proposal.get("toTier"),
    }


def set_sensitivity(
    current: Any,
    new: Any,
    *,
    approval: dict[str, Any] | None = None,
    root: Path | None = None,
    scope: str = "default",
    journal: bool = True,
) -> dict[str, Any]:
    """Explicit sensitivity setter with monotonic declassification enforcement."""
    proposal = propose_sensitivity_change(current, new)
    if proposal.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "cause": "sensitivity:invalid-transition",
            "proposal": proposal,
        }
    approval_check = _validate_approval(approval, proposal)
    if approval_check.get("verdict") != "pass":
        return {
            "verdict": "fail",
            "cause": approval_check.get("cause"),
            "humanGate": approval_check.get("humanGate", HUMAN_GATE_COMMAND),
            "proposal": proposal,
        }
    to_tier = str(proposal["toTier"])
    journal_entry: dict[str, Any] | None = None
    if proposal.get("requiresApproval") and approval_check.get("approved") and root is not None:
        if journal:
            journal_entry = record_declassification_approval(
                root,
                stable_id=str(approval_check["stableId"]),
                from_tier=str(proposal["fromTier"]),
                to_tier=to_tier,
                approver=str(approval_check["approver"]),
                scope=scope,
                reason=str((approval or {}).get("reason") or ""),
            )
    return {
        "verdict": "pass",
        "fromTier": proposal.get("fromTier"),
        "toTier": to_tier,
        "action": proposal.get("action"),
        "journalEntry": journal_entry,
    }


def set_envelope_sensitivity(
    envelope: dict[str, Any],
    new_tier: Any,
    *,
    approval: dict[str, Any] | None = None,
    root: Path | None = None,
    scope: str = "default",
) -> dict[str, Any]:
    """Set envelope ``sensitivity`` via the monotonic setter; returns updated envelope on pass."""
    current = envelope.get("sensitivity")
    result = set_sensitivity(
        current,
        new_tier,
        approval=approval,
        root=root,
        scope=scope,
    )
    if result.get("verdict") != "pass":
        return result
    updated = dict(envelope)
    updated["sensitivity"] = result["toTier"]
    result["envelope"] = updated
    return result
