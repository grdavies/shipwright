"""PRD 333 phase 6 — planning-store semantic parity harness (R2, R11, R16)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from _planning_pkg_loader import load_submodule

_pc = load_submodule("provider_conformance")
ALLOWLISTED_PLANNING_STORE_DEGRADATIONS = _pc.ALLOWLISTED_PLANNING_STORE_DEGRADATIONS
MANDATORY_PLANNING_STORE_VERBS = _pc.MANDATORY_PLANNING_STORE_VERBS
NORMALIZED_PLANNING_STORE_ERRORS = _pc.NORMALIZED_PLANNING_STORE_ERRORS
PLANNING_STORE_CORPUS_SCENARIOS = _pc.PLANNING_STORE_CORPUS_SCENARIOS
PLANNING_STORE_DEFERRED_BACKENDS = _pc.PLANNING_STORE_DEFERRED_BACKENDS
PLANNING_STORE_MATRIX_VERSION = _pc.PLANNING_STORE_MATRIX_VERSION
PLANNING_STORE_SHIPPED_BACKENDS = _pc.PLANNING_STORE_SHIPPED_BACKENDS
collect_corpus_scenario_ids = _pc.collect_corpus_scenario_ids
is_degradation_allowlisted = _pc.is_degradation_allowlisted
load_planning_store_conformance_record = _pc.load_planning_store_conformance_record
planning_store_capability_matrix = _pc.planning_store_capability_matrix
planning_store_conformance_fixture_path = _pc.planning_store_conformance_fixture_path
planning_store_semantic_parity_evidence = _pc.planning_store_semantic_parity_evidence
refuse_undeclared_degradation = _pc.refuse_undeclared_degradation
refuse_unsupported_parity_claim = _pc.refuse_unsupported_parity_claim
run_planning_store_verb_suite = _pc.run_planning_store_verb_suite


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_mandatory_capability_matrix() -> None:
    """R2 — matrix defines every mandatory verb and matrix version."""
    matrix = planning_store_capability_matrix()
    assert matrix["matrixVersion"] == PLANNING_STORE_MATRIX_VERSION
    assert set(matrix["mandatoryVerbs"]) == set(MANDATORY_PLANNING_STORE_VERBS)
    assert "freeze" in matrix["mandatoryVerbs"]
    assert set(matrix["corpusScenarios"]) == PLANNING_STORE_CORPUS_SCENARIOS


def test_mandatory_verb_suite_in_repo_public() -> None:
    """R2/R16 — in-repo-public exercises put/get/exists/materialize/freeze."""
    root = _repo_root()
    suite = run_planning_store_verb_suite("in-repo-public", root)
    assert suite["verdict"] == "ok", suite.get("failedVerbs")
    for verb in MANDATORY_PLANNING_STORE_VERBS:
        assert suite["verbs"][verb]["verdict"] == "ok", verb


def test_optimistic_revision_conflict_is_normalized() -> None:
    """R16 — revision-conflict is a normalized planning-store error."""
    assert "revision-conflict" in NORMALIZED_PLANNING_STORE_ERRORS


def test_declared_degradation_allowlisted() -> None:
    """R16 — declared file-backed freeze degradation is on the allowlist."""
    assert is_degradation_allowlisted(
        "in-repo-public", "freeze", "frontmatter-hash-authoritative"
    )
    result = refuse_undeclared_degradation(
        "in-repo-public", "freeze", "frontmatter-hash-authoritative"
    )
    assert result["verdict"] == "ok"


def test_undeclared_degradation_refused() -> None:
    """R16 — undeclared degradation fails closed."""
    result = refuse_undeclared_degradation(
        "in-repo-public", "freeze", "silent-partial-write"
    )
    assert result["verdict"] == "fail"
    assert result["error"] == "undeclared-degradation"


def test_claim_requires_corpus_evidence() -> None:
    """R11 — parity claim without corpus scenario ids is refused."""
    claim = {
        "matrixVersion": PLANNING_STORE_MATRIX_VERSION,
        "backend": "in-repo-public",
        "verbs": {verb: {"verdict": "ok"} for verb in MANDATORY_PLANNING_STORE_VERBS},
        "corpusScenarioIds": [],
        "parityComplete": True,
    }
    result = refuse_unsupported_parity_claim(claim)
    assert result["verdict"] == "fail"
    assert any(f["error"] == "missing-corpus-evidence" for f in result["failures"])


def test_claim_requires_matrix_version() -> None:
    """R11 — stale matrix version refuses parity claim."""
    claim = {
        "matrixVersion": "1.0.0",
        "backend": "in-repo-public",
        "verbs": {verb: {"verdict": "ok"} for verb in MANDATORY_PLANNING_STORE_VERBS},
        "corpusScenarioIds": sorted(PLANNING_STORE_CORPUS_SCENARIOS),
        "parityComplete": True,
    }
    result = refuse_unsupported_parity_claim(claim)
    assert result["verdict"] == "fail"
    assert any(f["error"] == "stale-or-missing-matrix" for f in result["failures"])


def test_deferred_backend_cannot_claim_parity_complete() -> None:
    """R13 — deferred backends cannot claim parityComplete."""
    claim = {
        "matrixVersion": PLANNING_STORE_MATRIX_VERSION,
        "backend": "private-repo",
        "verbs": {verb: {"verdict": "ok"} for verb in MANDATORY_PLANNING_STORE_VERBS},
        "corpusScenarioIds": sorted(PLANNING_STORE_CORPUS_SCENARIOS),
        "parityComplete": True,
    }
    result = refuse_unsupported_parity_claim(claim)
    assert result["verdict"] == "fail"
    assert any(f["error"] == "deferred-backend-parity-claim" for f in result["failures"])


def test_corpus_scenario_binding() -> None:
    """R11 — eval corpus manifest exposes required planning-store scenarios."""
    root = _repo_root()
    corpus = collect_corpus_scenario_ids(root)
    assert corpus["verdict"] == "ok", corpus
    assert set(corpus["scenarioIds"]) >= PLANNING_STORE_CORPUS_SCENARIOS


def test_missing_corpus_evidence_fails_evidence_gate() -> None:
    """R11 — missing corpus manifest fails semantic parity evidence."""
    root = _repo_root()
    missing_root = root / ".cursor" / "sw-test-missing-corpus"
    missing_root.mkdir(parents=True, exist_ok=True)
    evidence = planning_store_semantic_parity_evidence(missing_root, "in-repo-public")
    assert evidence["verdict"] == "fail"
    assert any(f["phase"] == "corpus" for f in evidence["failures"])


@pytest.mark.parametrize("backend", sorted(PLANNING_STORE_SHIPPED_BACKENDS))
def test_shipped_backends_have_conformance_fixtures(backend: str) -> None:
    """R2 — each shipped backend has a green conformance record."""
    root = _repo_root()
    path = planning_store_conformance_fixture_path(root, backend)
    assert path.is_file(), f"missing conformance fixture for {backend}"
    record = load_planning_store_conformance_record(root, backend)
    assert record.get("verdict") == "ok", record
    assert record.get("matrixVersion") == PLANNING_STORE_MATRIX_VERSION
    assert set(record.get("corpusScenarioIds") or []) >= PLANNING_STORE_CORPUS_SCENARIOS


@pytest.mark.parametrize("backend", sorted(PLANNING_STORE_SHIPPED_BACKENDS))
def test_semantic_parity_evidence_green(backend: str) -> None:
    """R2/R11/R16 — recorded + live + corpus evidence must be green."""
    root = _repo_root()
    evidence = planning_store_semantic_parity_evidence(root, backend)
    assert evidence["verdict"] == "ok", evidence.get("failures")


def test_bundled_platform_scope_excludes_unrelated_providers() -> None:
    """D2 — planning-store parity evidence is scoped to store backends only."""
    matrix = planning_store_capability_matrix()
    backends = set(matrix["backends"])
    assert "github-issues" not in backends
    assert "gitlab" not in backends


def test_degradation_allowlist_is_exhaustive_for_deferred() -> None:
    """R16 — every deferred backend verb maps to backend-deferred-inert."""
    for backend in PLANNING_STORE_DEFERRED_BACKENDS:
        for verb in MANDATORY_PLANNING_STORE_VERBS:
            assert is_degradation_allowlisted(backend, verb, "backend-deferred-inert")


def test_capabilities_doc_declares_matrix_version() -> None:
    """R2 — CAPABILITIES.md frontmatter pins matrix version 2."""
    root = _repo_root()
    text = (root / "core/providers/planning-store/CAPABILITIES.md").read_text(encoding="utf-8")
    assert "matrixVersion: \"2.0.0\"" in text or 'matrixVersion: "2.0.0"' in text
    assert "frontmatter-hash-authoritative" in text
    for verb in MANDATORY_PLANNING_STORE_VERBS:
        assert f"`{verb}`" in text
