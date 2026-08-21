#!/usr/bin/env python3
"""Measurement-learning read surfaces for /sw-status (PRD 280 R10)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import workflow_intelligence as wi  # noqa: E402
from rule_effectiveness import recommendations_report  # noqa: E402


def collect_rule_effectiveness_summary(root: Path) -> dict[str, Any]:
    """Read-only rule lifecycle recommendations summary."""
    root = root.resolve()
    report = recommendations_report(root)
    recommendations = list(report.get("recommendations") or [])
    payload: dict[str, Any] = {
        "verdict": "pass",
        "readOnly": True,
        "present": bool(recommendations),
        "recommendationCount": int(report.get("recommendationCount") or 0),
        "safetyRefusals": list(report.get("safetyRefusals") or []),
        "auditHandoff": report.get("auditHandoff"),
        "reportCommand": report.get("reportCommand"),
        "generatedAt": report.get("generatedAt"),
    }
    if recommendations:
        payload["topRecommendations"] = [
            {
                "ruleId": item.get("ruleId"),
                "recommendation": item.get("recommendation"),
                "confidence": item.get("confidence"),
                "safetyBlocked": bool(item.get("safetyBlocked")),
            }
            for item in recommendations[:5]
            if isinstance(item, dict)
        ]
    return payload


def collect_cohort_drill_down(root: Path, *, cohort_key: str | None = None) -> dict[str, Any]:
    """Read-only workflow intelligence cohort drill-down."""
    root = root.resolve()
    store = wi.WorkflowIntelligenceStore(root)
    payload: dict[str, Any] = {
        "verdict": "pass",
        "readOnly": True,
        "present": False,
        "artifactRoot": wi.ARTIFACT_ROOT,
    }
    if cohort_key:
        key = cohort_key.strip()
        aggregate = store.resolve_aggregate(key)
        records = store.records_for_cohort(key)
        payload["present"] = bool(aggregate or records)
        payload["cohortKey"] = key
        if aggregate:
            payload["aggregate"] = aggregate
        payload["recordCount"] = len(records)
        payload["recentRuns"] = [
            {
                "graphRunId": record.get("graphRunId"),
                "deliverRunId": record.get("deliverRunId"),
                "updatedAt": record.get("updatedAt"),
                "metrics": record.get("metrics"),
            }
            for record in sorted(
                records,
                key=lambda item: str(item.get("updatedAt") or ""),
                reverse=True,
            )[:5]
        ]
        return payload

    cohorts = store.list_cohort_summaries()
    payload["present"] = bool(cohorts)
    payload["cohortCount"] = len(cohorts)
    payload["cohorts"] = cohorts[:10]
    return payload


def collect_measurement_learning_status(root: Path, *, cohort_key: str | None = None) -> dict[str, Any]:
    """Combined measurement-learning block for derive --json."""
    return {
        "verdict": "pass",
        "readOnly": True,
        "ruleEffectiveness": collect_rule_effectiveness_summary(root),
        "workflowIntelligence": collect_cohort_drill_down(root, cohort_key=cohort_key),
    }


def collect_export_handoff(
    root: Path,
    *,
    unit_id: str | None = None,
    phase_slug: str | None = None,
    run_id: str | None = None,
    handoff_degraded: bool = False,
    out_path: str | None = None,
) -> dict[str, Any]:
    """Read-only HandoffBundle export for /sw-status --export-handoff (PRD 280 R10)."""
    from handoff_bundle import export_bundle

    root = root.resolve()
    result = export_bundle(
        root,
        unit_id=unit_id,
        phase_slug=phase_slug,
        run_id=run_id,
        handoff_degraded=handoff_degraded,
    )
    if out_path and result.get("verdict") == "pass" and isinstance(result.get("bundle"), dict):
        destination = Path(out_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(result["bundle"], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        result = {**result, "path": str(destination.relative_to(root)) if destination.is_relative_to(root) else str(destination)}
    result["readOnly"] = True
    result["exportCommand"] = "python3 scripts/wave_status.py export-handoff"
    return result


def cmd_rule_effectiveness_summary(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    payload = collect_rule_effectiveness_summary(root)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("verdict") == "pass" else 20


def cmd_cohort_drill_down(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    payload = collect_cohort_drill_down(root, cohort_key=args.cohort_key or None)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("verdict") == "pass" else 20


def cmd_measurement_learning(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    payload = collect_measurement_learning_status(root, cohort_key=args.cohort_key or None)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("verdict") == "pass" else 20


def cmd_export_handoff(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve() if args.root else Path.cwd()
    payload = collect_export_handoff(
        root,
        unit_id=args.unit_id or None,
        phase_slug=args.phase_slug or None,
        run_id=args.run_id or None,
        handoff_degraded=bool(args.handoff_degraded),
        out_path=args.out or None,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    verdict = str(payload.get("verdict") or "")
    if verdict == "pass":
        return 0
    return 20


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measurement-learning status surfaces (PRD 280 R10)")
    parser.add_argument("--root", default="", help="Repository root (default: cwd)")
    sub = parser.add_subparsers(dest="command", required=True)

    summary = sub.add_parser(
        "rule-effectiveness-summary",
        help="Rule lifecycle recommendations summary (read-only)",
    )
    summary.set_defaults(func=cmd_rule_effectiveness_summary)

    drill = sub.add_parser(
        "cohort-drill-down",
        help="Workflow intelligence cohort drill-down (read-only)",
    )
    drill.add_argument("--cohort-key", default="")
    drill.set_defaults(func=cmd_cohort_drill_down)

    combined = sub.add_parser(
        "measurement-learning",
        help="Combined rule effectiveness + cohort drill-down block",
    )
    combined.add_argument("--cohort-key", default="")
    combined.set_defaults(func=cmd_measurement_learning)

    export_handoff = sub.add_parser(
        "export-handoff",
        help="Export portable HandoffBundle@v1 from durable state (read-only; PRD 280 R10)",
    )
    export_handoff.add_argument("--unit-id", default="")
    export_handoff.add_argument("--phase-slug", default="")
    export_handoff.add_argument("--run-id", default="")
    export_handoff.add_argument("--handoff-degraded", action="store_true")
    export_handoff.add_argument("--out", default="")
    export_handoff.set_defaults(func=cmd_export_handoff)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
