"""Adversarial rule verification helpers (PRD 064 R7/R8)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_SWEEP: dict[str, Any] = {"enabled": False}


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


def resolve_sweep_config(cfg: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_SWEEP)
    gap = (cfg or {}).get("gapCheck") if isinstance(cfg, dict) else None
    sweep = gap.get("ruleVerifierSweep") if isinstance(gap, dict) else None
    if isinstance(sweep, dict) and "enabled" in sweep:
        merged["enabled"] = bool(sweep.get("enabled"))
    return merged


def build_verifier_brief(rule: dict[str, Any], *, evidence: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    return {
        "role": "rule-verifier",
        "ruleId": rule.get("id") or rule.get("ruleId"),
        "ruleText": rule.get("text") or rule.get("body") or rule.get("content"),
        "evidence": evidence or {},
        "runId": run_id,
        "cleanContext": True,
        "instructions": (
            "Test whether this candidate rule is supported by the transcript/diff evidence. "
            'Return JSON: {"ruleId":"...","verdict":"supported|unsupported|inconclusive",'
            '"evidenceFor":[],"evidenceAgainst":[],"gaps":[]}'
        ),
    }


def build_skeptic_brief(rule: dict[str, Any], verifier_result: dict[str, Any], *, evidence: dict[str, Any] | None = None, run_id: str | None = None) -> dict[str, Any]:
    return {
        "role": "rule-skeptic",
        "ruleId": rule.get("id") or rule.get("ruleId"),
        "ruleText": rule.get("text") or rule.get("body") or rule.get("content"),
        "verifier": {
            "verdict": verifier_result.get("verdict"),
            "evidenceFor": verifier_result.get("evidenceFor") or [],
            "evidenceAgainst": verifier_result.get("evidenceAgainst") or [],
        },
        "evidence": evidence or {},
        "runId": run_id,
        "cleanContext": True,
        "instructions": (
            "Challenge false positives from the verifier. Filter unsupported promotion claims. "
            'Return JSON: {"ruleId":"...","verdict":"pass|fail|inconclusive","falsePositives":[],'
            '"residualRisks":[],"rationale":"..."}'
        ),
    }


def evaluate_verification(verifier_result: dict[str, Any], skeptic_result: dict[str, Any]) -> dict[str, Any]:
    verifier_verdict = str(verifier_result.get("verdict") or "inconclusive").lower()
    skeptic_verdict = str(skeptic_result.get("verdict") or "inconclusive").lower()
    promotion_ready = verifier_verdict == "supported" and skeptic_verdict == "pass"
    return {
        "ruleId": verifier_result.get("ruleId") or skeptic_result.get("ruleId"),
        "verifierVerdict": verifier_verdict,
        "skepticVerdict": skeptic_verdict,
        "promotionReady": promotion_ready,
        "humanGateRequired": True,
        "falsePositives": skeptic_result.get("falsePositives") or [],
        "residualRisks": skeptic_result.get("residualRisks") or [],
        "rationale": skeptic_result.get("rationale") or verifier_result.get("rationale") or "",
    }


def normalize_verifier_result(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "ruleId": raw.get("ruleId"),
        "verdict": raw.get("verdict") or "inconclusive",
        "evidenceFor": raw.get("evidenceFor") or [],
        "evidenceAgainst": raw.get("evidenceAgainst") or [],
        "gaps": raw.get("gaps") or [],
        "rationale": raw.get("rationale") or "",
    }


def normalize_skeptic_result(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "ruleId": raw.get("ruleId"),
        "verdict": raw.get("verdict") or "inconclusive",
        "falsePositives": raw.get("falsePositives") or [],
        "residualRisks": raw.get("residualRisks") or [],
        "rationale": raw.get("rationale") or "",
    }


def plan_rule_sweep(rules: list[dict[str, Any]]) -> dict[str, Any]:
    jobs = []
    for idx, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("id") or rule.get("ruleId") or f"rule-{idx + 1}")
        jobs.append({"jobId": f"verify-{idx + 1}", "ruleId": rule_id, "rule": {**rule, "id": rule_id}})
    return {"jobCount": len(jobs), "jobs": jobs, "mode": "fan-out-and-synthesize"}


def synthesize_sweep(job_results: list[dict[str, Any]]) -> dict[str, Any]:
    violations = [r for r in job_results if r.get("repeatViolation") is True]
    inconclusive = [r for r in job_results if str(r.get("verdict")) == "inconclusive"]
    passing = [r for r in job_results if str(r.get("verdict")) == "pass"]
    return {
        "verdict": "halt" if violations else ("inconclusive" if inconclusive else "pass"),
        "violationCount": len(violations),
        "inconclusiveCount": len(inconclusive),
        "passCount": len(passing),
        "violations": violations,
        "results": job_results,
    }


def evaluate_repeat_violation(rule: dict[str, Any], verifier_result: dict[str, Any]) -> dict[str, Any]:
    verdict = str(verifier_result.get("verdict") or "inconclusive").lower()
    repeat = verdict == "violation" or bool(verifier_result.get("repeatViolation"))
    return {
        "ruleId": rule.get("id") or rule.get("ruleId"),
        "verdict": "violation" if repeat else ("pass" if verdict == "compliant" else "inconclusive"),
        "repeatViolation": repeat,
        "rationale": verifier_result.get("rationale") or "",
        "evidence": verifier_result.get("evidence") or [],
    }
