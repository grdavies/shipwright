"""Workflow benchmark harness — case manifest corpus and paired eval runner (PRD 272 R17–R18)."""

from graph.benchmark.acceptance import evaluate_trace_acceptance, TraceEvidence
from graph.benchmark.fake_provider import FakeModelProvider
from graph.benchmark.manifest import (
    BenchmarkCase,
    BenchmarkManifest,
    default_manifest_path,
    load_manifest,
    validate_manifest,
    WORKFLOW_TYPES,
)
from graph.benchmark.runner import (
    BenchmarkMetrics,
    PairedEvalReport,
    PairedEvalRunner,
    run_fake_provider_lane,
)

__all__ = [
    "BenchmarkCase",
    "BenchmarkManifest",
    "BenchmarkMetrics",
    "FakeModelProvider",
    "PairedEvalReport",
    "PairedEvalRunner",
    "TraceEvidence",
    "WORKFLOW_TYPES",
    "default_manifest_path",
    "evaluate_trace_acceptance",
    "load_manifest",
    "run_fake_provider_lane",
    "validate_manifest",
]
