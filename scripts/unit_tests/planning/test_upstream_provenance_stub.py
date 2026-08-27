"""PRD 333 phase 9 — upstream provenance P2 spec stub (R7, R11, R13, R18)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import upstream_provenance as up


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _full_provenance_claim(*, provenance_complete: bool = True, parity_complete: bool = False) -> dict:
    return {
        "analyzer": up.ANALYZER_ID,
        "evidenceContractVersion": up.EVIDENCE_CONTRACT_VERSION,
        "dimensions": {dim: {"verdict": "ok"} for dim in up.MANDATORY_EVIDENCE_DIMENSIONS},
        "corpusScenarioIds": sorted(up.UPSTREAM_PROVENANCE_CORPUS_SCENARIOS),
        "provenanceComplete": provenance_complete,
        "parityComplete": parity_complete,
        "enabled": False,
        "shipped": False,
    }


def test_spec_only_boundary() -> None:
    """R7 — spec defines contract; stub validates inputs without analysis."""
    spec_path = _repo_root() / up.SPEC_REL_PATH
    assert spec_path.is_file()
    text = spec_path.read_text(encoding="utf-8")
    for heading in (
        "remote identity",
        "revision ancestry",
        "patch lineage",
        "confidence",
        "ambiguity",
        "unavailable-upstream",
        "evidence retention",
    ):
        assert heading in text.lower()

    registration = up.register_upstream_provenance_stub()
    assert registration["status"] == "not-enabled"
    assert registration["shipped"] is False
    assert registration["provenanceComplete"] is False

    result = up.analyze_upstream_provenance(
        remote_url="https://github.com/shipwright-fixtures/eval-greenfield-same-repo",
        revision="a8b5d8bff028833fde25e6031f847fd4ac82ee7e",
    )
    assert result["status"] == "not-enabled"
    assert result["providerAnalysis"] is False
    assert result["networkMutation"] is False
    assert result["provenanceComplete"] is False
    assert result["parityComplete"] is False


@pytest.mark.parametrize(
    ("remote", "error"),
    [
        ("", "malformed-remote"),
        ("http://insecure.example/repo", "malformed-remote"),
        ("https://user:pass@github.com/org/repo", "malformed-remote"),
        ("not-a-remote", "malformed-remote"),
    ],
)
def test_malformed_remote_rejected(remote: str, error: str) -> None:
    """R7/R11 — malformed remotes fail closed before any analysis."""
    with pytest.raises(up.UpstreamProvenanceError, match=error):
        up.validate_remote_url(remote)


@pytest.mark.parametrize(
    ("revision", "error"),
    [
        ("", "malformed-revision"),
        ("ZZZZZZZ", "malformed-revision"),
        ("abc", "malformed-revision"),
        ("g" * 40, "malformed-revision"),
    ],
)
def test_malformed_revision_rejected(revision: str, error: str) -> None:
    """R7 — malformed revisions fail closed."""
    with pytest.raises(up.UpstreamProvenanceError, match=error):
        up.validate_revision(revision)


def test_no_provider_or_network_analysis_occurs() -> None:
    """R11/R13 — analyze performs no provider or network mutation."""
    with mock.patch("subprocess.run") as run_mock, mock.patch(
        "urllib.request.urlopen"
    ) as urlopen_mock, mock.patch("socket.create_connection") as socket_mock:
        result = up.analyze_upstream_provenance(
            remote_url="https://github.com/shipwright-fixtures/eval-brownfield-separate-project",
            revision="094f7ab5c1d2e3f4a5b6c7d8e9f0a1b2c3d4e5f6",
            local_revision="45468534aabbccdd11223344556677889900aabb",
        )
    assert result["providerAnalysis"] is False
    assert result["networkMutation"] is False
    run_mock.assert_not_called()
    urlopen_mock.assert_not_called()
    socket_mock.assert_not_called()


def test_gate_blocks_complete_and_parity_without_corpus() -> None:
    """R11/R13 — complete/parity claims refused without corpus evidence."""
    complete = _full_provenance_claim(provenance_complete=True)
    complete_result = up.upstream_provenance_gate(complete)
    assert complete_result["verdict"] == "fail"
    errors = {item["error"] for item in complete_result["failures"]}
    assert "p2-stub-provenance-claim-refused" in errors

    parity = _full_provenance_claim(provenance_complete=False, parity_complete=True)
    parity_result = up.upstream_provenance_gate(parity)
    assert parity_result["verdict"] == "fail"
    assert "p2-stub-parity-claim-refused" in {f["error"] for f in parity_result["failures"]}

    partial = {
        "analyzer": up.ANALYZER_ID,
        "evidenceContractVersion": up.EVIDENCE_CONTRACT_VERSION,
        "dimensions": {"remote-identity": {"verdict": "ok"}},
        "corpusScenarioIds": [],
        "provenanceComplete": False,
        "parityComplete": False,
    }
    partial_result = up.upstream_provenance_gate(partial)
    assert partial_result["verdict"] == "fail"
    assert any(f["error"] == "missing-corpus-evidence" for f in partial_result["failures"])


def test_completion_boundary() -> None:
    """R13 — stub registered but not shipped; analyzer id stays out of shipped set."""
    registration = up.register_upstream_provenance_stub()
    assert registration["analyzerId"] == up.ANALYZER_ID
    assert registration["status"] == "not-enabled"
    assert up.ANALYZER_ID not in up.SHIPPED_PROVENANCE_ANALYZERS
    assert up.ANALYZER_ID in up.P2_PROVENANCE_STUBS
    assert up.ANALYZER_ID in up.ALL_PROVENANCE_ANALYZERS


def test_ambiguous_upstream_candidates_refused() -> None:
    """R7 — multiple candidate remotes surface ambiguity without analysis."""
    result = up.analyze_upstream_provenance(
        remote_url="https://github.com/shipwright-fixtures/eval-greenfield-same-repo",
        revision="a8b5d8bff028833fde25e6031f847fd4ac82ee7e",
        candidate_remotes=(
            "https://github.com/shipwright-fixtures/eval-greenfield-same-repo,"
            "https://github.com/shipwright-fixtures/eval-brownfield-separate-project"
        ),
    )
    assert result["verdict"] == "fail"
    assert result["error"] == "ambiguous-upstream"
    assert result["providerAnalysis"] is False


def test_sw_bootstrap_resolves_analyzer_stub() -> None:
    """Wiring — bootstrap resolves and runs upstream_provenance register."""
    root = _repo_root()
    proc = subprocess.run(
        [
            sys.executable,
            str(root / "scripts" / "sw_bootstrap.py"),
            "--root",
            str(root),
            "upstream_provenance.py",
            "--",
            "register",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["status"] == "not-enabled"
    assert payload["analyzerId"] == up.ANALYZER_ID
