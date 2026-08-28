"""PRD 333 R1, R11, R14 — eval corpus metrics, holdout isolation, and release gate."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

from eval_corpus import (  # noqa: E402
    EvalCorpusError,
    WAIVER_SCHEMA_VERSION,
    aggregate_metrics,
    canonical_json,
    evaluate_gate,
    execute_corpus,
    run_report,
    validate_waiver,
)
from eval_corpus_manifest import (  # noqa: E402
    EvalCorpusManifest,
    default_corpus_path,
    load_manifest,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _manifest() -> EvalCorpusManifest:
    return load_manifest(default_corpus_path(_repo_root()))


def _fixture_corpus() -> dict[str, Any]:
    return json.loads(default_corpus_path(_repo_root()).read_text(encoding="utf-8"))


def _valid_waiver(manifest: EvalCorpusManifest) -> dict[str, Any]:
    return {
        "schemaVersion": WAIVER_SCHEMA_VERSION,
        "manifestId": manifest.manifest_id,
        "corpusVersion": manifest.corpus_version,
        "attributedTo": "release-ops@example.com",
        "reason": "Known transient fixture drift; tracked in issue #1234.",
        "issuedAt": "2026-08-27T00:00:00Z",
        "covers": "release-gate",
    }


def test_deterministic_metrics() -> None:
    manifest = _manifest()
    first = run_report(manifest)
    second = run_report(manifest)
    assert canonical_json(first) == canonical_json(second)
    assert first["eval"]["scenarioPassRate"] == 1.0
    assert first["eval"]["falsePositiveRate"] == 0.0


def test_holdout_isolation() -> None:
    manifest = _manifest()
    eval_results = execute_corpus(manifest, include_holdout=False)
    assert all(not item.holdout for item in eval_results)
    eval_ids = {item.repository_id for item in eval_results}
    holdout_ids = {repo.repository_id for repo in manifest.holdout_repositories()}
    assert eval_ids.isdisjoint(holdout_ids)
    report = run_report(manifest)
    assert "holdout" in report
    assert report["eval"]["partition"] == "eval"
    assert report["holdout"]["partition"] == "holdout"
    eval_metrics = aggregate_metrics(manifest, eval_results, partition="eval")
    assert eval_metrics.scenario_count == len(eval_results)


def test_corpus_red_blocks_release() -> None:
    manifest = _manifest()
    raw = _fixture_corpus()
    raw["repositories"][0]["expectedOutcomes"][0]["status"] = "fail"
    broken = EvalCorpusManifest.from_dict(raw)
    report = run_report(broken)
    verdict = evaluate_gate(report, waiver=None, manifest=broken)
    assert verdict["verdict"] == "corpus-red"
    assert verdict["releaseReadiness"] == "blocked"
    assert verdict["cause"] == "corpus-red"


def test_malformed_waiver_rejected() -> None:
    manifest = _manifest()
    raw = _fixture_corpus()
    raw["repositories"][0]["expectedOutcomes"][0]["status"] = "fail"
    broken = EvalCorpusManifest.from_dict(raw)
    report = run_report(broken)
    with pytest.raises(EvalCorpusError, match="missing"):
        validate_waiver({"schemaVersion": WAIVER_SCHEMA_VERSION}, manifest=broken)
    verdict = evaluate_gate(
        report,
        waiver={"schemaVersion": "wrong", "manifestId": manifest.manifest_id},
        manifest=broken,
    )
    assert verdict["verdict"] == "corpus-red"
    assert "malformed-waiver" in str(verdict["cause"])


def test_attributable_waiver_acceptance() -> None:
    manifest = _manifest()
    raw = _fixture_corpus()
    raw["repositories"][0]["expectedOutcomes"][0]["status"] = "fail"
    broken = EvalCorpusManifest.from_dict(raw)
    report = run_report(broken)
    waiver = _valid_waiver(broken)
    validate_waiver(waiver, manifest=broken)
    verdict = evaluate_gate(report, waiver=waiver, manifest=broken)
    assert verdict["verdict"] == "waiver-accepted"
    assert verdict["releaseReadiness"] == "ready"
    assert verdict["waiverApplied"] is True


def test_release_green_or_waiver() -> None:
    manifest = _manifest()
    green = evaluate_gate(run_report(manifest), manifest=manifest)
    assert green["verdict"] == "green"
    assert green["releaseReadiness"] == "ready"
    raw = copy.deepcopy(_fixture_corpus())
    raw["repositories"][1]["expectedOutcomes"][0]["status"] = "fail"
    broken = EvalCorpusManifest.from_dict(raw)
    red = evaluate_gate(run_report(broken), manifest=broken)
    assert red["verdict"] == "corpus-red"
    waived = evaluate_gate(
        run_report(broken),
        waiver=_valid_waiver(broken),
        manifest=broken,
    )
    assert waived["verdict"] == "waiver-accepted"
