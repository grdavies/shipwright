"""Multi-hypothesis RCA fan-out helpers (PRD 064 R1/R2)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GENERATOR_SLOTS = ("logs", "diff", "data", "config")
MAX_GENERATORS = 4

DEFAULT_FANOUT: dict[str, Any] = {
    "enabled": False,
    "min_hypotheses": 3,
    "ambiguity_trigger": True,
    "max_width": 4,
}


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


def resolve_fanout_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_FANOUT)
    rca = (cfg or {}).get("rca") if isinstance(cfg, dict) else None
    fanout = rca.get("fanout") if isinstance(rca, dict) else None
    if isinstance(fanout, dict):
        for key in DEFAULT_FANOUT:
            if key in fanout:
                merged[key] = fanout[key]
    merged["max_width"] = min(int(merged.get("max_width") or 4), MAX_GENERATORS)
    merged["min_hypotheses"] = max(int(merged.get("min_hypotheses") or 3), 1)
    merged["enabled"] = bool(merged.get("enabled"))
    merged["ambiguity_trigger"] = bool(merged.get("ambiguity_trigger"))
    return merged


def _signal_text(signal: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("excerpt", "description", "reproSteps", "stack", "message"):
        val = signal.get(key)
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())
    logs = signal.get("logs")
    if isinstance(logs, list):
        parts.extend(str(x) for x in logs if str(x).strip())
    elif isinstance(logs, str) and logs.strip():
        parts.append(logs.strip())
    return "\n".join(parts)


def detect_ambiguity(signal: dict[str, Any]) -> dict[str, Any]:
    text = _signal_text(signal)
    markers: list[str] = []
    if signal.get("ambiguous") is True:
        markers.append("explicit-ambiguous-flag")
    if signal.get("type") == "user_report" and not str(signal.get("reproSteps") or "").strip():
        markers.append("user-report-without-repro")
    signatures = set(re.findall(r"(?:Error|Exception|FAIL|AssertionError)[:\s][^\n]+", text))
    if len(signatures) >= 2:
        markers.append("multiple-error-signatures")
    stacks = [line for line in text.splitlines() if line.strip().startswith("at ")]
    if len(stacks) >= 4:
        markers.append("deep-multi-frame-stack")
    conflicting = signal.get("conflictingEvidence")
    if isinstance(conflicting, list) and conflicting:
        markers.append("conflicting-evidence-classes")
    return {
        "ambiguous": bool(markers),
        "markers": markers,
        "errorSignatureCount": len(signatures),
    }


def partition_evidence(signal: dict[str, Any]) -> dict[str, Any]:
    partitions: dict[str, Any] = {}
    text = _signal_text(signal)
    if text:
        partitions["logs"] = {
            "slot": "logs",
            "excerpt": text[:12000],
            "signalType": signal.get("type"),
        }
    diff = signal.get("diff") or signal.get("recentDiff") or signal.get("deployRef")
    if isinstance(diff, str) and diff.strip():
        partitions["diff"] = {"slot": "diff", "excerpt": diff[:8000]}
    elif signal.get("type") == "deploy_log" and signal.get("deployRef"):
        partitions["diff"] = {
            "slot": "diff",
            "excerpt": str(signal.get("deployRef")),
            "source": "deploy_ref",
        }
    data = signal.get("data") or signal.get("runtime") or signal.get("metrics")
    if data:
        partitions["data"] = {"slot": "data", "payload": data}
    config_bits = signal.get("config") or signal.get("environment")
    if config_bits:
        partitions["config"] = {"slot": "config", "payload": config_bits}
    related = signal.get("relatedFiles")
    if isinstance(related, list) and related and "config" not in partitions:
        partitions["config"] = {
            "slot": "config",
            "payload": {"relatedFiles": related},
            "source": "related_files",
        }
    return partitions


def plan_generators(signal: dict[str, Any], fanout_cfg: dict[str, Any]) -> dict[str, Any]:
    partitions = partition_evidence(signal)
    width = min(int(fanout_cfg.get("max_width") or 4), MAX_GENERATORS, len(partitions) or 1)
    ordered_slots = [slot for slot in GENERATOR_SLOTS if slot in partitions][:width]
    generators = [
        {"id": f"gen-{idx + 1}", "slot": slot, "partition": partitions[slot]}
        for idx, slot in enumerate(ordered_slots)
    ]
    return {
        "mode": "fan-out" if generators else "single-context",
        "generatorCount": len(generators),
        "generators": generators,
        "partitions": partitions,
    }


def should_fanout(
    signal: dict[str, Any],
    fanout_cfg: dict[str, Any],
    *,
    initial_hypothesis_count: int | None = None,
) -> dict[str, Any]:
    if not fanout_cfg.get("enabled"):
        return {"useFanout": False, "reason": "disabled-default", "d5Gate": "single-context-default"}
    ambiguity = detect_ambiguity(signal)
    partitions = partition_evidence(signal)
    reasons: list[str] = []
    if fanout_cfg.get("ambiguity_trigger") and ambiguity["ambiguous"]:
        reasons.append("ambiguity-trigger")
    if initial_hypothesis_count is not None and initial_hypothesis_count < int(
        fanout_cfg.get("min_hypotheses") or 3
    ):
        reasons.append("below-min-hypotheses")
    if len(partitions) >= 2:
        reasons.append("multi-evidence-class")
    if not reasons:
        return {
            "useFanout": False,
            "reason": "d5-not-met",
            "d5Gate": "single-context",
            "ambiguity": ambiguity,
            "partitionCount": len(partitions),
        }
    plan = plan_generators(signal, fanout_cfg)
    return {
        "useFanout": True,
        "reason": "+".join(reasons),
        "d5Gate": "fan-out",
        "ambiguity": ambiguity,
        "plan": plan,
    }


def build_generator_brief(
    generator: dict[str, Any],
    *,
    signal_type: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "role": "generator",
        "generatorId": generator.get("id"),
        "slot": generator.get("slot"),
        "signalType": signal_type,
        "runId": run_id,
        "cleanContext": True,
        "partition": generator.get("partition") or {},
        "instructions": (
            "Form ranked hypotheses using only this evidence partition. "
            'Return JSON: {"hypotheses":[{"id":"h1","statement":"...","evidenceFor":[],"evidenceAgainst":[]}]}'
        ),
    }


def _hypothesis_key(item: dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", str(item.get("statement") or item.get("text") or "").strip().lower())


def synthesize_hypotheses(generator_results: list[dict[str, Any]], *, min_hypotheses: int = 3) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for result in generator_results:
        gen_id = result.get("generatorId") or result.get("id") or "unknown"
        for hyp in result.get("hypotheses") or []:
            if not isinstance(hyp, dict):
                continue
            key = _hypothesis_key(hyp)
            if not key:
                continue
            entry = merged.setdefault(
                key,
                {
                    "id": hyp.get("id") or f"merged-{len(merged) + 1}",
                    "statement": hyp.get("statement") or hyp.get("text") or key,
                    "evidenceFor": [],
                    "evidenceAgainst": [],
                    "sources": [],
                },
            )
            entry["sources"].append(gen_id)
            for side in ("evidenceFor", "evidenceAgainst"):
                vals = hyp.get(side) or []
                if isinstance(vals, list):
                    entry[side].extend(str(v) for v in vals if str(v).strip())
    hypotheses = list(merged.values())
    for hyp in hypotheses:
        hyp["evidenceFor"] = sorted(set(hyp.get("evidenceFor") or []))
        hyp["evidenceAgainst"] = sorted(set(hyp.get("evidenceAgainst") or []))
        hyp["sources"] = sorted(set(hyp.get("sources") or []))
    survivors = [h for h in hypotheses if not h.get("invalidated")]
    return {
        "hypothesisCount": len(hypotheses),
        "survivors": survivors,
        "meetsMin": len(hypotheses) >= min_hypotheses,
        "hypotheses": hypotheses,
    }


def build_refuter_brief(
    hypothesis: dict[str, Any],
    *,
    signal_summary: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    return {
        "role": "refuter",
        "hypothesisId": hypothesis.get("id"),
        "statement": hypothesis.get("statement"),
        "signalSummary": signal_summary or {},
        "runId": run_id,
        "cleanContext": True,
        "instructions": (
            "Attempt to disprove this hypothesis. Focus on missing causal links and contradictory evidence. "
            'Return JSON: {"verdict":"survives|refuted|inconclusive","causalChainComplete":bool,'
            '"disproof":[],"residualEvidence":[]}'
        ),
    }


def evaluate_refutation(hypothesis: dict[str, Any], refuter_result: dict[str, Any]) -> dict[str, Any]:
    verdict = str(refuter_result.get("verdict") or "inconclusive").lower()
    causal_complete = bool(refuter_result.get("causalChainComplete"))
    refuted = verdict == "refuted"
    survives = verdict == "survives" and causal_complete
    if verdict == "survives" and not causal_complete:
        verdict = "inconclusive"
    return {
        "hypothesisId": hypothesis.get("id"),
        "statement": hypothesis.get("statement"),
        "verdict": verdict,
        "refuted": refuted,
        "survives": survives,
        "causalChainComplete": causal_complete,
        "disproof": refuter_result.get("disproof") or [],
        "residualEvidence": refuter_result.get("residualEvidence") or [],
    }


def evaluate_survivors(refutation_results: list[dict[str, Any]]) -> dict[str, Any]:
    survivors = [r for r in refutation_results if r.get("survives")]
    refuted = [r for r in refutation_results if r.get("refuted")]
    inconclusive = [r for r in refutation_results if str(r.get("verdict")) == "inconclusive"]
    top = survivors[0] if survivors else None
    return {
        "verdict": "survivors" if survivors else ("all-refuted" if refuted else "inconclusive"),
        "survivorCount": len(survivors),
        "refutedCount": len(refuted),
        "inconclusiveCount": len(inconclusive),
        "survivors": survivors,
        "topSurvivor": top,
        "routeReady": bool(survivors),
    }


def normalize_generator_result(raw: dict[str, Any], *, generator_id: str | None = None) -> dict[str, Any]:
    hyps = raw.get("hypotheses")
    if not isinstance(hyps, list):
        hyps = []
    return {
        "generatorId": generator_id or raw.get("generatorId") or raw.get("id"),
        "hypotheses": [h for h in hyps if isinstance(h, dict)],
    }


def normalize_refuter_result(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": raw.get("verdict") or "inconclusive",
        "causalChainComplete": bool(raw.get("causalChainComplete")),
        "disproof": raw.get("disproof") or [],
        "residualEvidence": raw.get("residualEvidence") or [],
    }
