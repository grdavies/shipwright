"""Mechanical risk detectors for required-capability injection (PRD 272)."""

from graph.detectors.compiler import attach_injection_metadata, compile_verification_nodes
from graph.detectors.evidence import (
    collect_injection_evidence,
    explain_payload,
    record_false_positive_override,
)
from graph.detectors.registry import (
    CAPABILITY_API,
    CAPABILITY_AUTH,
    CAPABILITY_MIGRATION,
    CAPABILITY_STANDARD_REVIEW,
    CAPABILITY_SUPPLY_CHAIN,
    DETECTOR_API,
    DETECTOR_AUTH,
    DETECTOR_MIGRATION,
    DETECTOR_SUPPLY_CHAIN,
)
from graph.detectors.result import (
    DetectorParseError,
    DetectorResult,
    parse_detector_result,
    union_required_capability_ids,
)
from graph.detectors.runner import run_detectors, summarize_detection

__all__ = [
    "CAPABILITY_API",
    "CAPABILITY_AUTH",
    "CAPABILITY_MIGRATION",
    "CAPABILITY_STANDARD_REVIEW",
    "CAPABILITY_SUPPLY_CHAIN",
    "DETECTOR_API",
    "DETECTOR_AUTH",
    "DETECTOR_MIGRATION",
    "DETECTOR_SUPPLY_CHAIN",
    "DetectorParseError",
    "DetectorResult",
    "attach_injection_metadata",
    "collect_injection_evidence",
    "compile_verification_nodes",
    "explain_payload",
    "parse_detector_result",
    "record_false_positive_override",
    "run_detectors",
    "summarize_detection",
    "union_required_capability_ids",
]
