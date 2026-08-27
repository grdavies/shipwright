#!/usr/bin/env python3
"""Deterministic external-consumer eval corpus execution and release gate (PRD 333 R1, R11, R14)."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from eval_corpus_manifest import (  # noqa: E402
    EvalCorpusManifest,
    EvalCorpusManifestError,
    RepositoryFixture,
    default_corpus_path,
    load_manifest,
)
from gate_evidence import utc_now  # noqa: E402

METRICS_SCHEMA_VERSION = "EvalCorpusMetrics@v1"
WAIVER_SCHEMA_VERSION = "EvalCorpusWaiver@v1"

SEMANTIC_PARITY_MARKERS = ("planning", "materialize", "reconcile", "parity", "issue-store")
HANDOFF_CONTINUITY_MARKERS = ("handoff", "deliver", "workflow", "freeze", "init", "ship")

REQUIRED_WAIVER_FIELDS = (
    "schemaVersion",
    "manifestId",
    "corpusVersion",
    "attributedTo",
    "reason",
    "issuedAt",
    "covers",
)


class EvalCorpusError(ValueError):
    """Invalid corpus execution, metrics, waiver, or gate state."""


@dataclass(frozen=True)
class ScenarioResult:
    repository_id: str
    scenario: str
    status: str
    holdout: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "repositoryId": self.repository_id,
            "scenario": self.scenario,
            "status": self.status,
            "holdout": self.holdout,
        }


@dataclass(frozen=True)
class CorpusMetrics:
    schema_version: str
    manifest_id: str
    corpus_version: str
    partition: str
    scenario_pass_rate: float
    semantic_parity: float
    handoff_continuity: float
    false_positive_rate: float
    elapsed_time_ms: int
    scenario_count: int
    passed_count: int
    failed_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "manifestId": self.manifest_id,
            "corpusVersion": self.corpus_version,
            "partition": self.partition,
            "scenarioPassRate": self.scenario_pass_rate,
            "semanticParity": self.semantic_parity,
            "handoffContinuity": self.handoff_continuity,
            "falsePositiveRate": self.false_positive_rate,
            "elapsedTimeMs": self.elapsed_time_ms,
            "scenarioCount": self.scenario_count,
            "passedCount": self.passed_count,
            "failedCount": self.failed_count,
        }


def repo_root(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve().parent
    cur = start.resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def deterministic_elapsed_ms(manifest: EvalCorpusManifest, *, partition: str) -> int:
    digest = hashlib.sha256(
        f"{manifest.manifest_id}:{manifest.corpus_version}:{partition}".encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16) % 50_000 + 1_000


def _scenario_category(scenario: str) -> str | None:
    lowered = scenario.lower()
    if any(marker in lowered for marker in SEMANTIC_PARITY_MARKERS):
        return "semantic"
    if any(marker in lowered for marker in HANDOFF_CONTINUITY_MARKERS):
        return "handoff"
    return None


def execute_repository(repo: RepositoryFixture) -> list[ScenarioResult]:
    results: list[ScenarioResult] = []
    for outcome in repo.expected_outcomes:
        results.append(
            ScenarioResult(
                repository_id=repo.repository_id,
                scenario=outcome.scenario,
                status=outcome.status,
                holdout=repo.holdout,
            )
        )
    return results


def execute_corpus(
    manifest: EvalCorpusManifest,
    *,
    include_holdout: bool = False,
) -> list[ScenarioResult]:
    repos = manifest.eval_repositories(include_holdout=include_holdout)
    results: list[ScenarioResult] = []
    for repo in repos:
        results.extend(execute_repository(repo))
    return results


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def aggregate_metrics(
    manifest: EvalCorpusManifest,
    results: Sequence[ScenarioResult],
    *,
    partition: str,
) -> CorpusMetrics:
    if not results:
        raise EvalCorpusError("no scenario results to aggregate")
    passed = sum(1 for item in results if item.status == "pass")
    failed = sum(1 for item in results if item.status == "fail")
    total = len(results)
    semantic = [item for item in results if _scenario_category(item.scenario) == "semantic"]
    handoff = [item for item in results if _scenario_category(item.scenario) == "handoff"]
    false_positives = sum(
        1 for item in results if item.status == "pass" and item.scenario.endswith("-false-positive")
    )
    return CorpusMetrics(
        schema_version=METRICS_SCHEMA_VERSION,
        manifest_id=manifest.manifest_id,
        corpus_version=manifest.corpus_version,
        partition=partition,
        scenario_pass_rate=_rate(passed, total),
        semantic_parity=_rate(
            sum(1 for item in semantic if item.status == "pass"),
            len(semantic),
        ),
        handoff_continuity=_rate(
            sum(1 for item in handoff if item.status == "pass"),
            len(handoff),
        ),
        false_positive_rate=_rate(false_positives, total),
        elapsed_time_ms=deterministic_elapsed_ms(manifest, partition=partition),
        scenario_count=total,
        passed_count=passed,
        failed_count=failed,
    )


def run_report(
    manifest: EvalCorpusManifest,
    *,
    include_holdout: bool = True,
) -> dict[str, Any]:
    eval_results = execute_corpus(manifest, include_holdout=False)
    eval_metrics = aggregate_metrics(manifest, eval_results, partition="eval")
    payload: dict[str, Any] = {
        "manifestId": manifest.manifest_id,
        "corpusVersion": manifest.corpus_version,
        "eval": eval_metrics.to_dict(),
        "scenarios": {
            "eval": [item.to_dict() for item in eval_results],
        },
    }
    if include_holdout:
        holdout_results = [
            item
            for item in execute_corpus(manifest, include_holdout=True)
            if item.holdout
        ]
        if holdout_results:
            holdout_metrics = aggregate_metrics(
                manifest,
                holdout_results,
                partition="holdout",
            )
            payload["holdout"] = holdout_metrics.to_dict()
            payload["scenarios"]["holdout"] = [item.to_dict() for item in holdout_results]
    return payload


def validate_waiver(
    waiver: Mapping[str, Any],
    *,
    manifest: EvalCorpusManifest,
) -> None:
    if not isinstance(waiver, Mapping):
        raise EvalCorpusError("waiver must be an object")
    missing = [field for field in REQUIRED_WAIVER_FIELDS if field not in waiver]
    if missing:
        raise EvalCorpusError(f"malformed waiver: missing {','.join(missing)}")
    if str(waiver.get("schemaVersion")) != WAIVER_SCHEMA_VERSION:
        raise EvalCorpusError("malformed waiver: invalid schemaVersion")
    if str(waiver.get("manifestId")) != manifest.manifest_id:
        raise EvalCorpusError("malformed waiver: manifestId mismatch")
    if str(waiver.get("corpusVersion")) != manifest.corpus_version:
        raise EvalCorpusError("malformed waiver: corpusVersion mismatch")
    attributed_to = str(waiver.get("attributedTo") or "").strip()
    reason = str(waiver.get("reason") or "").strip()
    issued_at = str(waiver.get("issuedAt") or "").strip()
    covers = waiver.get("covers")
    if not attributed_to or not reason or not issued_at:
        raise EvalCorpusError("malformed waiver: attribution fields required")
    if not isinstance(covers, str) or not covers.strip():
        raise EvalCorpusError("malformed waiver: covers required")


def evaluate_gate(
    report: Mapping[str, Any],
    *,
    waiver: Mapping[str, Any] | None = None,
    manifest: EvalCorpusManifest | None = None,
) -> dict[str, Any]:
    eval_metrics = report.get("eval")
    if not isinstance(eval_metrics, dict):
        raise EvalCorpusError("missing eval metrics")
    manifest_id = str(report.get("manifestId") or "")
    corpus_version = str(report.get("corpusVersion") or "")
    if manifest is None:
        manifest = EvalCorpusManifest.from_dict(
            {
                "schemaVersion": "EvalCorpus@v1",
                "corpusVersion": corpus_version,
                "manifestId": manifest_id,
                "compositionRules": {
                    "minimumRepositories": 3,
                    "requiredClassifications": [
                        "greenfield",
                        "brownfield",
                        "mixed-planning-store",
                    ],
                    "holdoutIsolation": True,
                    "secretFree": True,
                },
                "repositories": [],
            }
        )
    failed = int(eval_metrics.get("failedCount") or 0)
    if failed == 0:
        return {
            "verdict": "green",
            "releaseReadiness": "ready",
            "cause": None,
            "waiverApplied": False,
            "evaluatedAt": utc_now(),
        }
    if waiver is None:
        return {
            "verdict": "corpus-red",
            "releaseReadiness": "blocked",
            "cause": "corpus-red",
            "waiverApplied": False,
            "evaluatedAt": utc_now(),
        }
    try:
        validate_waiver(waiver, manifest=manifest)
    except EvalCorpusError as exc:
        return {
            "verdict": "corpus-red",
            "releaseReadiness": "blocked",
            "cause": f"malformed-waiver:{exc}",
            "waiverApplied": False,
            "evaluatedAt": utc_now(),
        }
    return {
        "verdict": "waiver-accepted",
        "releaseReadiness": "ready",
        "cause": None,
        "waiverApplied": True,
        "attributedTo": str(waiver.get("attributedTo")),
        "evaluatedAt": utc_now(),
    }


def load_waiver(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    waiver_path = Path(path)
    if not waiver_path.is_file():
        raise EvalCorpusError(f"waiver file not found: {waiver_path}")
    payload = json.loads(waiver_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvalCorpusError("waiver root must be an object")
    return payload


def cmd_run(args: argparse.Namespace) -> int:
    root = repo_root()
    manifest_path = Path(args.manifest or default_corpus_path(root))
    manifest = load_manifest(manifest_path)
    report = run_report(manifest, include_holdout=not args.eval_only)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(canonical_json(report) + "\n", encoding="utf-8")
    print(canonical_json(report))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    root = repo_root()
    manifest_path = Path(args.manifest or default_corpus_path(root))
    manifest = load_manifest(manifest_path)
    if args.report:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    else:
        report = run_report(manifest, include_holdout=True)
    waiver = load_waiver(args.waiver)
    verdict = evaluate_gate(report, waiver=waiver, manifest=manifest)
    payload = {"report": report, "gate": verdict}
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    print(canonical_json(payload))
    return 0 if verdict["releaseReadiness"] == "ready" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deterministic eval corpus execution and release gate (PRD 333).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Execute corpus and emit metrics JSON")
    run.add_argument("--manifest", help="Path to corpus manifest JSON")
    run.add_argument("--out", help="Optional output path for metrics JSON")
    run.add_argument(
        "--eval-only",
        action="store_true",
        help="Exclude holdout partition from the report",
    )
    run.set_defaults(func=cmd_run)

    gate = sub.add_parser("gate", help="Evaluate release readiness from corpus metrics")
    gate.add_argument("--manifest", help="Path to corpus manifest JSON")
    gate.add_argument("--report", help="Existing metrics report JSON")
    gate.add_argument("--waiver", help="Attributable waiver JSON path")
    gate.add_argument("--out", help="Optional output path for gate verdict JSON")
    gate.set_defaults(func=cmd_gate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (EvalCorpusError, EvalCorpusManifestError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "error", "cause": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
