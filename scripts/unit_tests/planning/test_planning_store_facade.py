"""PRD 085 R18 — operator-projection live-probe producers + adapter-complete claim."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_store as ps
import planning_store_facade as facade


def test_capability_matrix_includes_live_probe_fields() -> None:
    matrix = ps.operator_projection_capability_matrix()
    assert "linearAnswerable" in matrix
    assert "projectsAnswerable" in matrix
    assert isinstance(matrix["linearAnswerable"], bool)
    assert isinstance(matrix["projectsAnswerable"], bool)


def test_adapter_complete_claim_false_when_not_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(facade, "_linear_live_client_wired", lambda: False)
    monkeypatch.setattr(facade, "_projects_live_client_wired", lambda: False)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is False
    assert claim["answerable"] == {"linear": False, "github-projects": False}


def test_adapter_complete_claim_true_when_both_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(facade, "_linear_live_client_wired", lambda: True)
    monkeypatch.setattr(facade, "_projects_live_client_wired", lambda: True)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is True
    assert claim["answerable"] == {"linear": True, "github-projects": True}


def test_adapter_complete_claim_false_when_only_linear_wired(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(facade, "_linear_live_client_wired", lambda: True)
    monkeypatch.setattr(facade, "_projects_live_client_wired", lambda: False)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is False


def test_adapter_complete_claim_false_when_live_flag_without_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenLinear:
        LIVE_CLIENT = True

    class _BrokenProjects:
        LIVE_CLIENT = True

    monkeypatch.setitem(sys.modules, "planning_linear_client", _BrokenLinear())
    monkeypatch.setitem(sys.modules, "planning_github_projects_v2", _BrokenProjects())
    from _planning_pkg_loader import load_submodule

    linear_mod = load_submodule("providers.linear")
    projects_mod = load_submodule("providers.github_projects")
    assert linear_mod.live_client_wired() is False
    assert projects_mod.live_client_wired() is False
    monkeypatch.setattr(facade, "_linear_live_client_wired", linear_mod.live_client_wired)
    monkeypatch.setattr(facade, "_projects_live_client_wired", projects_mod.live_client_wired)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is False
