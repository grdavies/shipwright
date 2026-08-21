#!/usr/bin/env python3
"""External issue triage lifecycle (PRD 280 phase 1 / gap-323)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from planning_canonical import GAP_LABEL_OPEN, SOURCE_TAG_LABEL_PREFIX, type_label

EXTERNAL_INTAKE_MARKER = re.compile(
    r"<!--\s*sw-external-intake:\s*(\{.*?\})\s*-->",
    re.DOTALL,
)
SOURCE_EXTERNAL_LABEL = f"{SOURCE_TAG_LABEL_PREFIX}external"
EXTERNAL_INTAKE_STATE_PREFIX = "sw:external-intake:"
EXTERNAL_INTAKE_OUTCOMES = frozenset({"brief", "question", "closure"})

EXTERNAL_INTAKE_STATES = frozenset(
    {
        "received",
        "classified",
        "duplicate-candidate",
        "verifying",
        "actionable",
        "blocked-reporter",
        "ready-brief",
        "closed",
    }
)

VALID_TRANSITIONS: dict[str, frozenset[str]] = {
    "received": frozenset({"classified"}),
    "classified": frozenset({"duplicate-candidate", "verifying"}),
    "duplicate-candidate": frozenset({"closed", "verifying"}),
    "verifying": frozenset({"actionable", "blocked-reporter", "ready-brief", "closed"}),
    "actionable": frozenset({"ready-brief", "closed"}),
    "blocked-reporter": frozenset({"verifying", "closed"}),
    "ready-brief": frozenset({"closed"}),
    "closed": frozenset(),
}

TXN_VERBS = frozenset(
    {
        "external-intake-receive",
        "external-intake-classify",
        "external-intake-duplicate-check",
        "external-intake-verify",
        "external-intake-actionability",
        "external-intake-promote",
        "external-intake-ask-reporter",
        "external-intake-close",
    }
)

VERB_TO_STATE: dict[str, str] = {
    "external-intake-receive": "received",
    "external-intake-classify": "classified",
    "external-intake-duplicate-check": "duplicate-candidate",
    "external-intake-verify": "verifying",
    "external-intake-actionability": "actionable",
    "external-intake-promote": "ready-brief",
    "external-intake-ask-reporter": "blocked-reporter",
    "external-intake-close": "closed",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_external_intake_block(body: str) -> dict[str, Any]:
    match = EXTERNAL_INTAKE_MARKER.search(body or "")
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def render_external_intake_block(block: dict[str, Any]) -> str:
    payload = json.dumps(block, sort_keys=True, separators=(",", ":"))
    return f"<!-- sw-external-intake: {payload} -->"


def upsert_external_intake_block(body: str, block: dict[str, Any]) -> str:
    marker = render_external_intake_block(block)
    if EXTERNAL_INTAKE_MARKER.search(body or ""):
        return EXTERNAL_INTAKE_MARKER.sub(marker, body, count=1)
    stripped = (body or "").rstrip()
    return f"{stripped}\n\n{marker}\n" if stripped else f"{marker}\n"


def external_intake_state_label(state: str) -> str:
    return f"{EXTERNAL_INTAKE_STATE_PREFIX}{state}"


def strip_external_intake_state_labels(labels: list[str]) -> list[str]:
    return [label for label in labels if not label.startswith(EXTERNAL_INTAKE_STATE_PREFIX)]


def sync_external_intake_labels(labels: list[str], state: str) -> list[str]:
    base = strip_external_intake_state_labels(list(labels))
    out = sorted(set(base) | {SOURCE_EXTERNAL_LABEL, external_intake_state_label(state)})
    return out


def validate_transition(current: str, target: str) -> None:
    if current not in EXTERNAL_INTAKE_STATES:
        raise ValueError(f"invalid-current-state:{current}")
    if target not in EXTERNAL_INTAKE_STATES:
        raise ValueError(f"invalid-target-state:{target}")
    allowed = VALID_TRANSITIONS.get(current, frozenset())
    if target not in allowed and current != target:
        raise ValueError(f"illegal-transition:{current}->{target}")


def append_transition(block: dict[str, Any], *, verb: str, from_state: str, to_state: str, note: str = "") -> dict[str, Any]:
    transitions = list(block.get("transitions") or [])
    transitions.append(
        {
            "at": utc_now(),
            "verb": verb,
            "from": from_state,
            "to": to_state,
            "note": note,
        }
    )
    updated = dict(block)
    updated["state"] = to_state
    updated["transitions"] = transitions
    return updated


def initial_external_intake_block(*, signal_id: str, signal_class: str = "unknown") -> dict[str, Any]:
    return {
        "state": "received",
        "signalId": signal_id,
        "signalClass": signal_class,
        "transitions": [
            {
                "at": utc_now(),
                "verb": "external-intake-receive",
                "from": "",
                "to": "received",
                "note": "intake",
            }
        ],
    }


def gap_promotion_labels(
    *,
    unit_id: str,
    priority: str = "medium",
    tier: str = "build",
    gap_class: str = "external",
) -> list[str]:
    return sorted(
        {
            type_label("gap"),
            GAP_LABEL_OPEN,
            f"sw:unit:{unit_id}",
            f"sw:gap-priority:{priority}",
            f"sw:gap-tier:{tier}",
            f"sw:gap-class:{gap_class}",
        }
    )


def outcome_for_verb(verb: str) -> str | None:
    if verb == "external-intake-promote":
        return "brief"
    if verb == "external-intake-ask-reporter":
        return "question"
    if verb == "external-intake-close":
        return "closure"
    return None
