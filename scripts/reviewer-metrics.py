#!/usr/bin/env python3
"""Operator CLI for reviewer effectiveness label ingest and export (PRD 273 R8, R11)."""
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

from graph.reviewer_metrics.cohort import CohortIdentity  # noqa: E402
from graph.reviewer_metrics.elo import (  # noqa: E402
    ContestOutcome,
    EloConfig,
    PairwiseContest,
    ReviewerRating,
    initial_ratings,
    recompute_from_contests,
)
from graph.reviewer_metrics.export import build_export_report  # noqa: E402
from graph.reviewer_metrics.independence import ReviewerAxisIdentity  # noqa: E402
from graph.reviewer_metrics.persistence import build_metadata_record  # noqa: E402
from graph.reviewer_metrics.provenance import ActorClass, ProvenanceRecord, label_with_provenance  # noqa: E402
from graph.reviewer_metrics.store_adapter import ReviewerMetricsStoreAdapter  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


def _repo_root() -> Path:
    import subprocess

    proc = subprocess.run(
        ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path.cwd()


def _parse_label_verdict(raw: str) -> tuple[str, str]:
    normalized = raw.strip().lower()
    if normalized in {"tp", "true-positive", "true_positive"}:
        return "confirmed", "exogenous-human"
    if normalized in {"fp", "false-positive", "false_positive"}:
        return "rejected", "exogenous-human"
    raise ValueError(f"unsupported label verdict: {raw!r}")


def cmd_label_ingest(args: argparse.Namespace) -> int:
    terminal_status, match_reason = _parse_label_verdict(args.verdict)
    records = [
        ProvenanceRecord(
            actor_class=ActorClass.OPERATOR,
            actor_id=args.operator,
            source="reviewer-metrics-cli",
            recorded_at=args.recorded_at or utc_now(),
        )
    ]
    label = label_with_provenance(
        finding_id=args.finding,
        run_id=args.run,
        provenance_records=records,
        attribution_window=args.window,
        match_reason=match_reason,
        terminal_status=terminal_status,
        provenance_summary=f"operator:{args.operator}",
    )
    if label is None:
        return _emit(
            {
                "verdict": "fail",
                "action": "label-ingest",
                "error": "provenance-insufficient",
            },
            exit_code=20,
        )

    metadata = build_metadata_record(
        persona_id=args.persona,
        model_id=args.model,
        surface=args.surface,
        attribution_window=args.window,
        finding_id=args.finding,
        run_id=args.run,
        terminal_status=terminal_status,
        match_reason=match_reason,
        outcome_kind="label",
        recorded_at=args.recorded_at or utc_now(),
        provenance_summary=f"operator:{args.operator}",
        dedup_key=label.dedup_key,
    )
    adapter = ReviewerMetricsStoreAdapter(_repo_root(), may_egress=False)
    journal = {
        "runId": args.run,
        "findingId": args.finding,
        "verdict": "label-ingest",
        "operator": args.operator,
    }
    event = adapter.persist_metadata(metadata, journal_entry=journal)
    return _emit(
        {
            "verdict": "pass",
            "action": "label-ingest",
            "label": label.to_dict(),
            "eventId": event.event_id,
        }
    )


def _cohort_from_fixture(payload: dict[str, Any]) -> CohortIdentity:
    cohort = payload.get("cohort") or {}
    return CohortIdentity(
        persona_version=str(cohort.get("personaVersion", "persona-v1")),
        prompt_version=str(cohort.get("promptVersion", "prompt-v1")),
        model_version=str(cohort.get("modelVersion", "model-v1")),
        schema_version=int(cohort.get("schemaVersion", 1)),
        policy_version=str(cohort.get("policyVersion", "policy-v1")),
    )


def cmd_acceptance_fixture(args: argparse.Namespace) -> int:
    fixture_path = Path(args.fixture)
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    cohort = _cohort_from_fixture(payload)
    reviewers = [str(item) for item in payload.get("reviewers") or []]
    if len(reviewers) < 2:
        return _emit(
            {"verdict": "fail", "action": "acceptance-fixture", "error": "need>=2-reviewers"},
            exit_code=20,
        )

    contests: list[PairwiseContest] = []
    for item in payload.get("contests") or []:
        outcome = ContestOutcome(str(item["outcome"]))
        contests.append(
            PairwiseContest(
                str(item["reviewerA"]),
                str(item["reviewerB"]),
                outcome,
                cohort,
            )
        )

    config = EloConfig(k_factor=float(payload.get("kFactor", 32.0)))
    before = initial_ratings(reviewers, cohort, config=config)
    after = recompute_from_contests(contests, reviewers, cohort, config=config)
    expected = payload.get("expectedDelta") or {}
    tolerance = float(payload.get("tolerance", 1.0))
    deltas: dict[str, float] = {}
    failures: list[str] = []
    for reviewer_id in reviewers:
        delta = after[reviewer_id].rating - before[reviewer_id].rating
        deltas[reviewer_id] = delta
        if reviewer_id in expected:
            target = float(expected[reviewer_id])
            if abs(delta - target) > tolerance:
                failures.append(
                    f"{reviewer_id}: delta {delta:.4f} outside tolerance of {target:.4f}±{tolerance}"
                )

    if failures:
        return _emit(
            {
                "verdict": "fail",
                "action": "acceptance-fixture",
                "deltas": deltas,
                "failures": failures,
            },
            exit_code=20,
        )
    return _emit(
        {
            "verdict": "pass",
            "action": "acceptance-fixture",
            "deltas": deltas,
            "tolerance": tolerance,
        }
    )


def cmd_export_query(args: argparse.Namespace) -> int:
    fixture_path = Path(args.fixture) if args.fixture else None
    if fixture_path and fixture_path.is_file():
        payload = json.loads(fixture_path.read_text(encoding="utf-8"))
        cohort = _cohort_from_fixture(payload)
        ratings = tuple(
            ReviewerRating(
                reviewer_id=str(item["reviewerId"]),
                rating=float(item["rating"]),
                cohort=cohort,
                contests_played=int(item.get("contestsPlayed", 0)),
            )
            for item in payload.get("ratings") or []
        )
        identities = tuple(
            ReviewerAxisIdentity(
                persona_id=str(item.get("personaId", "")),
                model_id=str(item.get("modelId", "")),
                prompt_template_id=str(item.get("promptTemplateId", "")),
                cluster_id=str(item.get("clusterId", "")),
            )
            for item in payload.get("identities") or []
        )
    else:
        return _emit(
            {
                "verdict": "fail",
                "action": "export-query",
                "error": "fixture-required-for-export",
            },
            exit_code=20,
        )

    report = build_export_report(
        ratings,
        identities,
        top_n=int(args.top),
        bottom_n=int(args.bottom),
        min_n=int(args.min_n),
    )
    return _emit({"verdict": "pass", "action": "export-query", "report": report.to_dict()})


def cmd_stabilize_status(_args: argparse.Namespace) -> int:
    """Stub stabilize hook — advisory reviewer metrics never gate stabilize."""
    return _emit(
        {
            "verdict": "pass",
            "action": "stabilize-stub",
            "gating": False,
            "note": "reviewer-metrics offline/advisory only",
        }
    )


def cmd_ci_hook(_args: argparse.Namespace) -> int:
    """Stub CI hook — no reviewer-metrics CI integration in v1."""
    return _emit(
        {
            "verdict": "pass",
            "action": "ci-stub",
            "gating": False,
            "note": "reviewer-metrics CI hook is a no-op stub",
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reviewer effectiveness metrics CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    label = sub.add_parser("label", help="Operator label ingest")
    label_sub = label.add_subparsers(dest="label_cmd", required=True)
    ingest = label_sub.add_parser("ingest", help="Ingest operator TP/FP label")
    ingest.add_argument("--finding", required=True)
    ingest.add_argument("--run", required=True)
    ingest.add_argument("--persona", required=True)
    ingest.add_argument("--model", required=True)
    ingest.add_argument("--surface", default="sw-review")
    ingest.add_argument("--window", required=True)
    ingest.add_argument("--verdict", required=True, help="tp|fp")
    ingest.add_argument("--operator", required=True)
    ingest.add_argument("--recorded-at", default="")
    ingest.set_defaults(func=cmd_label_ingest)

    acceptance = sub.add_parser("acceptance", help="Fixture acceptance helpers")
    acceptance_sub = acceptance.add_subparsers(dest="acceptance_cmd", required=True)
    fixture = acceptance_sub.add_parser("fixture", help="Fixture→Elo delta acceptance")
    fixture.add_argument("--fixture", required=True)
    fixture.set_defaults(func=cmd_acceptance_fixture)

    export = sub.add_parser("export", help="Metadata-only export")
    export_sub = export.add_subparsers(dest="export_cmd", required=True)
    query = export_sub.add_parser("query", help="Top/bottom export without transcripts")
    query.add_argument("--fixture", required=True)
    query.add_argument("--top", type=int, default=3)
    query.add_argument("--bottom", type=int, default=3)
    query.add_argument("--min-n", type=int, default=10)
    query.set_defaults(func=cmd_export_query)

    stabilize = sub.add_parser("stabilize", help="Stabilize integration stub")
    stabilize_sub = stabilize.add_subparsers(dest="stabilize_cmd", required=True)
    status = stabilize_sub.add_parser("status", help="Non-gating stabilize status stub")
    status.set_defaults(func=cmd_stabilize_status)

    ci = sub.add_parser("ci", help="CI integration stub")
    ci_sub = ci.add_subparsers(dest="ci_cmd", required=True)
    hook = ci_sub.add_parser("hook", help="Non-gating CI hook stub")
    hook.set_defaults(func=cmd_ci_hook)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":
    from _sw.cli import run_module_main

    run_module_main(main)
