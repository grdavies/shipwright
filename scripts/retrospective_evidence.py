"""PRD 350 retrospective evidence helpers (R25–R28).

Primary evidence source is ``wave_journal.read_events`` — callers must not open
``events.jsonl`` directly. Memory candidates are observation-only
(``pending_human_review``); never synthesise rules/policy from event summaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from memory_observation_gate import OBSERVATION_STATUS, write_observation
from wave_journal import read_events

BLOCKER_RESOLVED_MARKER = "blocker resolved"


def load_retrospective_evidence(
    run_id: str,
    *,
    root: Path,
    event_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load capture evidence via ``read_events`` only (R25, R26)."""
    types = event_types or ["blocker", "milestone", "discovery"]
    return read_events(run_id, event_types=types, root=root)


def unresolved_blockers(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify blockers with no subsequent ``blocker resolved`` milestone (R27).

    Events with ``provenanceKind: inferred`` are flagged as lower confidence.
    """
    unresolved: list[dict[str, Any]] = []
    for idx, event in enumerate(events):
        if event.get("eventType") != "blocker":
            continue
        eid = event.get("eventId")
        resolved = False
        for later in events[idx + 1 :]:
            if later.get("eventType") != "milestone":
                continue
            summary = str(later.get("summary") or "").lower()
            if BLOCKER_RESOLVED_MARKER in summary:
                resolved = True
                break
        if resolved:
            continue
        row = {
            "eventId": eid,
            "blockerCondition": event.get("blockerCondition")
            or event.get("summary"),
            "phaseId": event.get("phaseId"),
            "timestamp": event.get("timestamp"),
            "lowerConfidence": event.get("provenanceKind") == "inferred",
        }
        unresolved.append(row)
    return unresolved


def memory_candidates_pending_review(
    events: list[dict[str, Any]],
    *,
    root: Path,
    run_id: str,
) -> list[dict[str, Any]]:
    """Surface memory candidates only as pending_human_review observations (R28).

    Routes discovery/milestone summaries through observation mode — never writes
    rules/policy.
    """
    candidates: list[dict[str, Any]] = []
    for event in events:
        if event.get("eventType") not in {"discovery", "milestone"}:
            continue
        summary = str(event.get("summary") or "").strip()
        if not summary:
            continue
        existing = event.get("memoryObservationRef")
        if isinstance(existing, str) and existing.startswith("observations/"):
            candidates.append(
                {
                    "eventId": event.get("eventId"),
                    "summary": summary,
                    "status": OBSERVATION_STATUS,
                    "observationRef": existing,
                }
            )
            continue
        result = write_observation(
            root,
            summary=summary,
            source_event_id=str(event.get("eventId") or "") or None,
            run_id=run_id,
        )
        candidates.append(
            {
                "eventId": event.get("eventId"),
                "summary": summary,
                "status": OBSERVATION_STATUS,
                "observationRef": result.get("observationRef"),
            }
        )
    return candidates


def render_retrospective_markdown(
    run_id: str,
    *,
    root: Path,
) -> str:
    """Render retrospective sections required by R25–R28."""
    events = load_retrospective_evidence(run_id, root=root)
    blockers = unresolved_blockers(events)
    memories = memory_candidates_pending_review(events, root=root, run_id=run_id)

    lines: list[str] = [
        f"# Retrospective evidence (run `{run_id}`)",
        "",
        "Evidence loaded via `wave_journal.read_events` (no direct events.jsonl reads).",
        "",
        "### Unresolved Blockers",
        "",
    ]
    if not blockers:
        lines.append("_None._")
    else:
        for b in blockers:
            conf = " (lower confidence — inferred)" if b.get("lowerConfidence") else ""
            lines.append(
                f"- `{b.get('eventId')}` phase=`{b.get('phaseId')}` "
                f"at `{b.get('timestamp')}`: {b.get('blockerCondition')}{conf}"
            )
    lines.extend(
        [
            "",
            "## Memory Candidates (pending_human_review)",
            "",
            "These are observation-state only — not confirmed policy/rules.",
            "",
        ]
    )
    if not memories:
        lines.append("_None._")
    else:
        for m in memories:
            lines.append(
                f"- `{m.get('eventId')}` status=`{m.get('status')}` "
                f"ref=`{m.get('observationRef')}`: {m.get('summary')}"
            )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Render retrospective evidence from capture events")
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    events = load_retrospective_evidence(args.run_id, root=root)
    payload = {
        "runId": args.run_id,
        "events": events,
        "unresolvedBlockers": unresolved_blockers(events),
        "memoryCandidates": memory_candidates_pending_review(
            events, root=root, run_id=args.run_id
        ),
        "markdown": render_retrospective_markdown(args.run_id, root=root),
    }
    if args.json:
        print(json.dumps({k: v for k, v in payload.items() if k != "markdown"}, indent=2))
    else:
        print(payload["markdown"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
