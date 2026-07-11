"""Bounded tournament primitive helpers (PRD 064 R5/R6)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TOURNAMENT: dict[str, Any] = {
    "enabled": False,
    "n": 3,
    "cost_ceiling": 0,
}

DEFAULT_RUBRIC = [
    "fit-to-requirements",
    "feasibility",
    "risk",
    "clarity",
]

MAX_ATTEMPTS = 8


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_workflow_config(root: Path) -> dict[str, Any]:
    root = root.resolve()
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return {}


def resolve_tournament_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_TOURNAMENT)
    tournament = (cfg or {}).get("tournament") if isinstance(cfg, dict) else None
    if isinstance(tournament, dict):
        for key in DEFAULT_TOURNAMENT:
            if key in tournament:
                merged[key] = tournament[key]
    merged["enabled"] = bool(merged.get("enabled"))
    merged["n"] = min(max(int(merged.get("n") or 3), 2), MAX_ATTEMPTS)
    ceiling = merged.get("cost_ceiling")
    merged["cost_ceiling"] = float(ceiling) if ceiling not in (None, "", False) else 0
    return merged


def should_run_tournament(
    divergence: dict[str, Any],
    tournament_cfg: dict[str, Any],
) -> dict[str, Any]:
    if not tournament_cfg.get("enabled"):
        return {"useTournament": False, "reason": "disabled-default"}
    candidates = divergence.get("candidates") or []
    if not isinstance(candidates, list):
        candidates = []
    viable = [c for c in candidates if isinstance(c, dict) and str(c.get("id") or c.get("label") or "").strip()]
    if len(viable) < 2:
        return {
            "useTournament": False,
            "reason": "insufficient-candidates",
            "candidateCount": len(viable),
        }
    return {
        "useTournament": True,
        "reason": "divergence-selection",
        "candidateCount": len(viable),
        "attemptCount": min(int(tournament_cfg.get("n") or 3), len(viable), MAX_ATTEMPTS),
    }


def plan_attempts(
    divergence: dict[str, Any],
    tournament_cfg: dict[str, Any],
) -> dict[str, Any]:
    gate = should_run_tournament(divergence, tournament_cfg)
    candidates = [c for c in (divergence.get("candidates") or []) if isinstance(c, dict)]
    count = int(gate.get("attemptCount") or tournament_cfg.get("n") or 3)
    count = min(max(count, 2), MAX_ATTEMPTS, len(candidates) or count)
    selected = candidates[:count]
    attempts = [
        {
            "id": f"attempt-{idx + 1}",
            "candidateId": str(item.get("id") or f"candidate-{idx + 1}"),
            "label": str(item.get("label") or item.get("title") or f"Option {idx + 1}"),
            "seed": idx + 1,
        }
        for idx, item in enumerate(selected)
    ]
    return {
        "mode": "tournament" if gate.get("useTournament") else "skipped",
        "attemptCount": len(attempts),
        "attempts": attempts,
        "rubric": list(DEFAULT_RUBRIC),
        "gate": gate,
        "prompt": divergence.get("prompt") or divergence.get("question") or "",
        "contextRef": divergence.get("contextRef"),
    }


def build_attempt_brief(
    attempt: dict[str, Any],
    *,
    divergence: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    div = divergence or {}
    return {
        "role": "attempt",
        "attemptId": attempt.get("id"),
        "candidateId": attempt.get("candidateId"),
        "label": attempt.get("label"),
        "runId": run_id,
        "cleanContext": True,
        "prompt": div.get("prompt") or div.get("question") or "",
        "constraints": div.get("constraints") or [],
        "instructions": (
            "Develop this divergence option in isolation. Do not read other attempts. "
            'Return JSON: {"attemptId":"...","summary":"...","proposal":"...","tradeoffs":[],"risks":[]}'
        ),
    }


def build_initial_pairings(attempt_ids: list[str]) -> list[dict[str, Any]]:
    pairings: list[dict[str, Any]] = []
    idx = 0
    match_no = 1
    while idx < len(attempt_ids):
        left = attempt_ids[idx]
        if idx + 1 < len(attempt_ids):
            pairings.append(
                {
                    "matchId": f"match-{match_no}",
                    "round": 1,
                    "a": left,
                    "b": attempt_ids[idx + 1],
                    "bye": False,
                }
            )
            idx += 2
        else:
            pairings.append(
                {
                    "matchId": f"match-{match_no}",
                    "round": 1,
                    "a": left,
                    "b": None,
                    "bye": True,
                }
            )
            idx += 1
        match_no += 1
    return pairings


def build_bracket(plan: dict[str, Any]) -> dict[str, Any]:
    attempt_ids = [str(a.get("id")) for a in (plan.get("attempts") or []) if isinstance(a, dict)]
    pairings = build_initial_pairings(attempt_ids)
    return {
        "attemptIds": attempt_ids,
        "round": 1,
        "pairings": pairings,
        "completedMatches": [],
        "winners": [],
    }


def build_judge_brief(
    match: dict[str, Any],
    *,
    attempt_a: dict[str, Any],
    attempt_b: dict[str, Any] | None,
    rubric: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "role": "judge",
        "matchId": match.get("matchId"),
        "round": match.get("round"),
        "runId": run_id,
        "cleanContext": True,
        "rubric": rubric or list(DEFAULT_RUBRIC),
        "attemptA": {
            "id": attempt_a.get("id"),
            "summary": attempt_a.get("summary") or attempt_a.get("proposal"),
            "tradeoffs": attempt_a.get("tradeoffs") or [],
        },
        "attemptB": None
        if attempt_b is None
        else {
            "id": attempt_b.get("id"),
            "summary": attempt_b.get("summary") or attempt_b.get("proposal"),
            "tradeoffs": attempt_b.get("tradeoffs") or [],
        },
        "instructions": (
            "Score each rubric dimension for A and B (0-5). Pick the winner with rationale. "
            'Return JSON: {"matchId":"...","scores":{"a":{},"b":{}},"winnerId":"...","rationale":"..."}'
        ),
    }


def evaluate_match(match: dict[str, Any], judge_result: dict[str, Any]) -> dict[str, Any]:
    winner = str(judge_result.get("winnerId") or "").strip()
    bye = bool(match.get("bye"))
    if bye and not winner:
        winner = str(match.get("a") or "")
    valid_ids = {str(match.get("a") or ""), str(match.get("b") or "")} - {""}
    if winner not in valid_ids and not bye:
        return {
            "matchId": match.get("matchId"),
            "verdict": "invalid",
            "winnerId": None,
            "rationale": judge_result.get("rationale") or "missing-winner",
        }
    return {
        "matchId": match.get("matchId"),
        "verdict": "complete",
        "winnerId": winner,
        "rationale": str(judge_result.get("rationale") or "").strip(),
        "scores": judge_result.get("scores") or {},
    }


def advance_bracket(bracket: dict[str, Any], match_results: list[dict[str, Any]]) -> dict[str, Any]:
    winners = [str(r.get("winnerId")) for r in match_results if r.get("winnerId")]
    winners = [w for w in winners if w]
    next_round = int(bracket.get("round") or 1) + 1
    if len(winners) <= 1:
        champion = winners[0] if winners else None
        return {
            "complete": True,
            "round": bracket.get("round"),
            "winnerId": champion,
            "pairings": [],
            "completedMatches": (bracket.get("completedMatches") or []) + match_results,
        }
    pairings = build_initial_pairings(winners)
    for pairing in pairings:
        pairing["round"] = next_round
    return {
        "complete": False,
        "round": next_round,
        "winnerId": None,
        "pairings": pairings,
        "completedMatches": (bracket.get("completedMatches") or []) + match_results,
        "attemptIds": bracket.get("attemptIds") or winners,
    }


def persist_result(
    out_path: Path,
    *,
    plan: dict[str, Any],
    bracket: dict[str, Any],
    winner: dict[str, Any],
    rationale: str,
) -> dict[str, Any]:
    payload = {
        "writtenAt": utc_now(),
        "mode": plan.get("mode"),
        "winner": winner,
        "rationale": rationale,
        "attemptCount": plan.get("attemptCount"),
        "bracket": {
            "round": bracket.get("round"),
            "completedMatches": bracket.get("completedMatches") or [],
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def normalize_attempt_result(raw: dict[str, Any], *, attempt_id: str | None = None) -> dict[str, Any]:
    return {
        "id": attempt_id or raw.get("attemptId") or raw.get("id"),
        "summary": raw.get("summary") or "",
        "proposal": raw.get("proposal") or raw.get("summary") or "",
        "tradeoffs": raw.get("tradeoffs") or [],
        "risks": raw.get("risks") or [],
    }


def normalize_judge_result(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "matchId": raw.get("matchId"),
        "winnerId": raw.get("winnerId"),
        "rationale": raw.get("rationale") or "",
        "scores": raw.get("scores") or {},
    }


def attempt_lookup(attempts: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(a.get("id")): a for a in attempts if isinstance(a, dict) and a.get("id")}


def champion_from_attempts(attempts: list[dict[str, Any]], winner_id: str) -> dict[str, Any]:
    lookup = attempt_lookup(attempts)
    winner = lookup.get(winner_id) or {"id": winner_id}
    return {
        "attemptId": winner_id,
        "candidateId": winner.get("candidateId"),
        "label": winner.get("label"),
        "summary": winner.get("summary") or winner.get("proposal"),
    }
