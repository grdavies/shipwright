"""PRD 090 R3 — github issues provider conformance + shipped evidence regression."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_store as ps
import planning_store_facade as ps_facade
from _planning_pkg_loader import load_submodule

_pc = load_submodule("provider_conformance")
CONFORMANCE_DIMENSIONS = _pc.CONFORMANCE_DIMENSIONS
CONFORMANCE_GATED_PROVIDERS = _pc.CONFORMANCE_GATED_PROVIDERS
conformance_evidence = _pc.conformance_evidence
conformance_fixture_path = _pc.conformance_fixture_path
load_conformance_record = _pc.load_conformance_record
run_conformance_suite = _pc.run_conformance_suite
write_conformance_record = _pc.write_conformance_record


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def _fixture_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")


def test_github_conformance_suite_green() -> None:
    """R3 — github provider passes the full conformance contract."""
    root = _repo_root()
    suite = run_conformance_suite("github-issues", root)
    assert suite["verdict"] == "ok", suite.get("failedDimensions")
    for dim in CONFORMANCE_DIMENSIONS:
        assert suite["dimensions"][dim]["verdict"] == "ok", dim


def test_github_conformance_record_matches_live_evidence() -> None:
    """R3 — recorded github fixture matches live suite (regression guard)."""
    root = _repo_root()
    evidence = conformance_evidence(root, "github-issues")
    assert evidence["verdict"] == "ok", evidence.get("failures")


def test_shipped_providers_require_green_conformance_evidence() -> None:
    """R3 — SHIPPED_ISSUES_PROVIDERS equals providers with green recorded evidence."""
    root = _repo_root()
    expected = set()
    for provider in CONFORMANCE_GATED_PROVIDERS:
        record = load_conformance_record(root, provider)
        dims = record.get("dimensions")
        if record.get("verdict") == "ok" and isinstance(dims, dict):
            if all(
                isinstance(dims.get(dim), dict) and dims[dim].get("verdict") == "ok"
                for dim in CONFORMANCE_DIMENSIONS
            ):
                expected.add(provider)
    assert ps.SHIPPED_ISSUES_PROVIDERS == frozenset(expected)
    assert ps_facade.SHIPPED_ISSUES_PROVIDERS == frozenset(expected)


def test_shipped_status_cannot_drift_without_record() -> None:
    """R3 — adding a provider to shipped without a fixture is impossible."""
    root = _repo_root()
    for provider in CONFORMANCE_GATED_PROVIDERS:
        if provider in ps.SHIPPED_ISSUES_PROVIDERS:
            path = conformance_fixture_path(root, provider)
            assert path.is_file(), f"missing conformance record for shipped {provider}"
            record = json.loads(path.read_text(encoding="utf-8"))
            assert record.get("verdict") == "ok"


@pytest.mark.parametrize("provider", ["github-issues", "jira", "linear"])
def test_gated_providers_have_conformance_fixtures(provider: str) -> None:
    """Bootstrap — each gated provider has a committed green conformance record."""
    root = _repo_root()
    record = load_conformance_record(root, provider)
    assert record.get("verdict") == "ok", record
    suite = run_conformance_suite(provider, root)
    assert suite["verdict"] == "ok", suite.get("failedDimensions")
    evidence = conformance_evidence(root, provider)
    assert evidence["verdict"] == "ok", evidence.get("failures")


def _regenerate_fixture(provider: str) -> None:
    """Helper for refreshing committed conformance records (not run in CI)."""
    root = _repo_root()
    suite = run_conformance_suite(provider, root)
    if suite["verdict"] != "ok":
        raise SystemExit(suite)
    write_conformance_record(root, provider, suite)


if __name__ == "__main__":
    for prov in sorted(CONFORMANCE_GATED_PROVIDERS):
        _regenerate_fixture(prov)
        print(f"updated {conformance_fixture_path(_repo_root(), prov)}")
