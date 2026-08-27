#!/usr/bin/env python3
"""Upstream provenance P2 spec stub — inputs/evidence contract, fail-closed analyzer (PRD 333 phase 9)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _sw.cli import run_module_main

ANALYZER_ID = "upstream-provenance"
SPEC_REL_PATH = "core/providers/provenance/upstream.md"
PROGRAM_PRIORITY_ID = "upstream-provenance"
EVIDENCE_CONTRACT_VERSION = "1.0.0"

MANDATORY_EVIDENCE_DIMENSIONS: tuple[str, ...] = (
    "remote-identity",
    "revision-ancestry",
    "patch-lineage",
    "confidence",
    "ambiguity",
    "unavailable-upstream",
    "evidence-retention",
)

UPSTREAM_PROVENANCE_CORPUS_SCENARIOS: frozenset[str] = frozenset(
    {
        "upstream-lineage-resolve",
        "patch-lineage-fork",
        "upstream-unavailable-handling",
    }
)

NORMALIZED_PROVENANCE_REFUSALS: frozenset[str] = frozenset(
    {
        "malformed-remote",
        "malformed-revision",
        "malformed-patch-lineage",
        "identity-mismatch",
        "ancestry-unresolved",
        "patch-lineage-incomplete",
        "confidence-below-threshold",
        "ambiguous-upstream",
        "upstream-unavailable",
        "missing-evidence-retention",
        "missing-corpus-evidence",
        "not-enabled",
    }
)

SHIPPED_PROVENANCE_ANALYZERS: frozenset[str] = frozenset()
P2_PROVENANCE_STUBS: frozenset[str] = frozenset({ANALYZER_ID})
ALL_PROVENANCE_ANALYZERS: frozenset[str] = SHIPPED_PROVENANCE_ANALYZERS | P2_PROVENANCE_STUBS

PROVENANCE_CONFORMANCE_FIXTURES_REL = Path("scripts/test/fixtures/upstream-provenance")

HTTPS_REMOTE_RE = re.compile(
    r"^https://[A-Za-z0-9._-]+(?:/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=-]+)?/?$"
)
SCP_REMOTE_RE = re.compile(r"^git@[A-Za-z0-9._-]+:[A-Za-z0-9._~/\-]+(?:\.git)?$")
REVISION_RE = re.compile(r"^[0-9a-f]{7,40}$")
PATCH_SERIES_RE = re.compile(r"^[0-9a-f]{7,40}\.\.[0-9a-f]{7,40}$")


class UpstreamProvenanceError(ValueError):
    """Invalid upstream provenance inputs or gate state."""


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def validate_remote_url(remote_url: str) -> str:
    """Validate bounded remote identity input (R7, R11)."""
    raw = str(remote_url or "").strip()
    if not raw or " " in raw:
        raise UpstreamProvenanceError("malformed-remote")
    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.scheme != "https" or not parsed.netloc:
            raise UpstreamProvenanceError("malformed-remote")
        if parsed.username or parsed.password:
            raise UpstreamProvenanceError("malformed-remote")
        if not HTTPS_REMOTE_RE.match(raw):
            raise UpstreamProvenanceError("malformed-remote")
        return raw.rstrip("/")
    if not SCP_REMOTE_RE.match(raw):
        raise UpstreamProvenanceError("malformed-remote")
    return raw


def validate_revision(revision: str) -> str:
    """Validate bounded revision input (R7)."""
    rev = str(revision or "").strip().lower()
    if not REVISION_RE.match(rev):
        raise UpstreamProvenanceError("malformed-revision")
    return rev


def validate_patch_series(raw: str | None) -> str | None:
    if raw is None:
        return None
    series = str(raw).strip().lower()
    if not series:
        return None
    if not PATCH_SERIES_RE.match(series):
        raise UpstreamProvenanceError("malformed-patch-lineage")
    base, tip = series.split("..", 1)
    validate_revision(base)
    validate_revision(tip)
    return series


def validate_candidate_remotes(raw: str | None) -> list[str]:
    if raw is None or not str(raw).strip():
        return []
    remotes = [part.strip() for part in str(raw).split(",") if part.strip()]
    if len(remotes) > 8:
        raise UpstreamProvenanceError("ambiguous-upstream")
    return [validate_remote_url(item) for item in remotes]


def upstream_provenance_capability_matrix() -> dict[str, Any]:
    return {
        "evidenceContractVersion": EVIDENCE_CONTRACT_VERSION,
        "analyzer": ANALYZER_ID,
        "dimensions": list(MANDATORY_EVIDENCE_DIMENSIONS),
        "normalizedRefusals": sorted(NORMALIZED_PROVENANCE_REFUSALS),
        "corpusScenarios": sorted(UPSTREAM_PROVENANCE_CORPUS_SCENARIOS),
    }


def register_upstream_provenance_stub() -> dict[str, Any]:
    """Registration surface — metadata only, not enabled (R7, R13, R18)."""
    matrix = upstream_provenance_capability_matrix()
    return {
        "analyzerId": ANALYZER_ID,
        "status": "not-enabled",
        "shipped": False,
        "provenanceComplete": False,
        "parityComplete": False,
        "specPath": SPEC_REL_PATH,
        "programPriorityId": PROGRAM_PRIORITY_ID,
        "evidenceContractVersion": matrix["evidenceContractVersion"],
        "mandatoryDimensions": list(MANDATORY_EVIDENCE_DIMENSIONS),
        "corpusScenarios": sorted(UPSTREAM_PROVENANCE_CORPUS_SCENARIOS),
        "normalizedRefusals": sorted(NORMALIZED_PROVENANCE_REFUSALS),
    }


def upstream_provenance_gate(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on provenance or parity claims for the P2 stub (R7, R11, R13)."""
    failures: list[dict[str, Any]] = []
    analyzer = str(claim.get("analyzer") or claim.get("analyzerId") or "")
    if analyzer != ANALYZER_ID:
        failures.append({"field": "analyzer", "error": "unexpected-analyzer", "observed": analyzer})

    contract_version = str(claim.get("evidenceContractVersion") or "")
    if contract_version != EVIDENCE_CONTRACT_VERSION:
        failures.append(
            {
                "field": "evidenceContractVersion",
                "error": "stale-evidence-contract",
                "observed": contract_version,
                "expected": EVIDENCE_CONTRACT_VERSION,
            }
        )

    dimensions = claim.get("dimensions") or {}
    missing = [dim for dim in MANDATORY_EVIDENCE_DIMENSIONS if dim not in dimensions]
    for dim in missing:
        failures.append({"field": "dimensions", "error": "missing-evidence-dimension", "dimension": dim})

    corpus_ids = claim.get("corpusScenarioIds") or claim.get("corpusScenarios") or []
    if not isinstance(corpus_ids, (list, tuple, set)):
        corpus_ids = []
    missing_corpus = sorted(UPSTREAM_PROVENANCE_CORPUS_SCENARIOS - set(corpus_ids))
    for scenario in missing_corpus:
        failures.append(
            {"field": "corpusScenarioIds", "error": "missing-corpus-evidence", "scenario": scenario}
        )

    if claim.get("provenanceComplete") is True:
        failures.append({"field": "provenanceComplete", "error": "p2-stub-provenance-claim-refused"})
    if claim.get("parityComplete") is True:
        failures.append({"field": "parityComplete", "error": "p2-stub-parity-claim-refused"})
    if claim.get("enabled") is True or claim.get("status") == "enabled":
        failures.append({"field": "status", "error": "p2-stub-enablement-refused"})
    if claim.get("shipped") is True:
        failures.append({"field": "shipped", "error": "p2-stub-shipped-claim-refused"})

    return {
        "verdict": "ok" if not failures else "fail",
        "action": "upstream-provenance-gate",
        "analyzer": ANALYZER_ID,
        "failures": failures,
    }


def analyze_upstream_provenance(
    *,
    remote_url: str,
    revision: str,
    local_revision: str | None = None,
    patch_series: str | None = None,
    candidate_remotes: str | None = None,
) -> dict[str, Any]:
    """Validate bounded inputs and emit deterministic not-enabled response (R7, R13, R18)."""
    normalized_remote = validate_remote_url(remote_url)
    normalized_revision = validate_revision(revision)
    normalized_local = validate_revision(local_revision) if local_revision else None
    normalized_patch = validate_patch_series(patch_series)
    normalized_candidates = validate_candidate_remotes(candidate_remotes)

    if len(normalized_candidates) > 1:
        return {
            "verdict": "fail",
            "action": "upstream-provenance-analyze",
            "analyzer": ANALYZER_ID,
            "status": "not-enabled",
            "shipped": False,
            "provenanceComplete": False,
            "parityComplete": False,
            "networkMutation": False,
            "providerAnalysis": False,
            "error": "ambiguous-upstream",
            "inputs": {
                "remoteUrl": normalized_remote,
                "revision": normalized_revision,
                "localRevision": normalized_local,
                "patchSeries": normalized_patch,
                "candidateRemotes": normalized_candidates,
            },
        }

    return {
        "verdict": "ok",
        "action": "upstream-provenance-analyze",
        "analyzer": ANALYZER_ID,
        "status": "not-enabled",
        "shipped": False,
        "provenanceComplete": False,
        "parityComplete": False,
        "networkMutation": False,
        "providerAnalysis": False,
        "notice": "upstream-provenance is a P2 spec stub — analysis not enabled",
        "inputs": {
            "remoteUrl": normalized_remote,
            "revision": normalized_revision,
            "localRevision": normalized_local,
            "patchSeries": normalized_patch,
            "candidateRemotes": normalized_candidates,
        },
        "evidenceContractVersion": EVIDENCE_CONTRACT_VERSION,
        "mandatoryDimensions": list(MANDATORY_EVIDENCE_DIMENSIONS),
    }


def conformance_metadata_only() -> dict[str, Any]:
    payload = register_upstream_provenance_stub()
    payload["action"] = "upstream-provenance-conformance-metadata"
    return payload


def cmd_register(_args: argparse.Namespace) -> int:
    print(canonical_json(register_upstream_provenance_stub()))
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        payload = analyze_upstream_provenance(
            remote_url=args.remote,
            revision=args.revision,
            local_revision=args.local_revision,
            patch_series=args.patch_series,
            candidate_remotes=args.candidate_remotes,
        )
    except UpstreamProvenanceError as exc:
        print(
            canonical_json(
                {
                    "verdict": "fail",
                    "action": "upstream-provenance-analyze",
                    "analyzer": ANALYZER_ID,
                    "status": "not-enabled",
                    "networkMutation": False,
                    "providerAnalysis": False,
                    "error": str(exc),
                }
            ),
            file=sys.stderr,
        )
        return 2
    print(canonical_json(payload))
    return 0 if payload.get("verdict") == "ok" else 1


def cmd_gate(args: argparse.Namespace) -> int:
    claim_path = Path(args.claim)
    claim = json.loads(claim_path.read_text(encoding="utf-8"))
    result = upstream_provenance_gate(claim)
    print(canonical_json(result))
    return 0 if result["verdict"] == "ok" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upstream provenance P2 spec stub (PRD 333 phase 9).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    register = sub.add_parser("register", help="Emit stub registration metadata")
    register.set_defaults(func=cmd_register)

    analyze = sub.add_parser("analyze", help="Validate inputs and return not-enabled")
    analyze.add_argument("--remote", required=True, help="Canonical upstream remote URL")
    analyze.add_argument("--revision", required=True, help="Git commit SHA")
    analyze.add_argument("--local-revision", help="Optional local HEAD SHA")
    analyze.add_argument("--patch-series", help="Optional base..tip patch series")
    analyze.add_argument(
        "--candidate-remotes",
        help="Optional comma-separated candidate remotes for ambiguity probing",
    )
    analyze.set_defaults(func=cmd_analyze)

    gate = sub.add_parser("gate", help="Evaluate a provenance claim JSON file")
    gate.add_argument("claim", help="Path to claim JSON")
    gate.set_defaults(func=cmd_gate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    run_module_main(main)
