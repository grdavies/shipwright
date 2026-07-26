"""Host fixture realism: fail-loud unresolved, non-ok mocks, simulated tag (PRD 079 R16)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CORE_SCRIPTS = Path(__file__).resolve().parent.parent
if str(_CORE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_CORE_SCRIPTS))

from _sw.host._common import (  # noqa: E402
    HostFixtureError,
    fixture_dir,
    is_simulated_evidence,
    mock_fixture,
    mock_transport,
    reject_simulated_for_merge,
    tag_simulated,
    transport_status_code,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_mock_fixture_unresolved_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "missing-fixture-name")
    with pytest.raises(HostFixtureError, match="unresolved host fixture"):
        mock_fixture(_REPO_ROOT, "checks-missing-fixture-name")


def test_mock_fixture_no_checks_green_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "advisory-fail")
    payload = mock_fixture(_REPO_ROOT, "checks-advisory-fail")
    assert payload is not None
    assert payload.get("verdict") == "ok"
    with pytest.raises(HostFixtureError):
        mock_fixture(_REPO_ROOT, "checks-nonexistent-scenario")


def test_mock_fixture_tags_simulated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "green")
    payload = mock_fixture(_REPO_ROOT, "checks-green")
    assert is_simulated_evidence(payload)


def test_mock_transport_emits_status_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "github-green")
    payload = mock_transport(_REPO_ROOT, "https://api.github.com/repos/owner/repo")
    assert transport_status_code(payload) == 200
    assert payload.get("verdict") == "ok"
    assert is_simulated_evidence(payload)


def test_mock_transport_non_ok_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "envelope-auth-denied")
    payload = mock_transport(
        _REPO_ROOT,
        "https://api.github.com/repos/owner/repo/commits/abc123/check-runs",
    )
    assert transport_status_code(payload) == 401
    assert payload.get("verdict") == "fail"
    assert is_simulated_evidence(payload)


def test_mock_transport_unresolved_url_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "github-green")
    with pytest.raises(HostFixtureError, match="no transport mapping"):
        mock_transport(_REPO_ROOT, "https://api.github.com/unknown/path")


def test_mock_transport_missing_file_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "does-not-exist")
    with pytest.raises(HostFixtureError, match="unresolved transport fixture"):
        mock_transport(_REPO_ROOT, "https://api.github.com/repos/owner/repo")


def test_legacy_status_fixture_normalizes_status_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_HOST_FIXTURE", "legacy-status-only")
    payload = mock_transport(_REPO_ROOT, "https://api.github.com/repos/owner/repo")
    assert transport_status_code(payload) == 200


def test_reject_simulated_for_merge_outside_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("SW_HOST_FIXTURE", raising=False)
    with pytest.raises(HostFixtureError, match="simulated evidence cannot authorize merge"):
        reject_simulated_for_merge(tag_simulated({"verdict": "ok"}))


def test_reject_simulated_for_merge_allows_fixture_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("SW_HOST_FIXTURE", "green")
    reject_simulated_for_merge(tag_simulated({"verdict": "ok"}))


def test_fixture_dir_points_at_scripts_tree() -> None:
    expected = _REPO_ROOT / "scripts" / "test" / "fixtures" / "host"
    assert fixture_dir(_REPO_ROOT) == expected
    assert (fixture_dir(_REPO_ROOT) / "checks-green.json").is_file()
