"""PRD 066 phase 1 — operator-projection contract (R1, R3, R4, R31, R32)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_store as ps
import planning_store_facade as facade


def test_operator_projection_contract_surface_answers_r1() -> None:
    """R1 — facade exposes provider-agnostic projection ops + matrix for browse Q1–Q4."""
    contract = ps.operator_projection_contract()
    assert contract["verdict"] == "ok"
    assert contract["action"] == "operator-projection-contract"
    questions = {int(q["id"]) for q in contract["r1BrowseQuestions"]}
    assert questions == {1, 2, 3, 4}
    assert "capabilityMatrix" in contract
    ops = {op["name"] for op in contract["operations"]}
    assert "projection_refresh" in ops
    assert "probe_projection" in ops
    assert "operator_projection_contract" in ops


def test_capability_matrix_requires_linear_and_projects_for_r3() -> None:
    """R3 — adapter-complete claim requires both Linear and GitHub Projects backends."""
    contract = ps.operator_projection_contract()
    matrix = contract["capabilityMatrix"]
    backends = set(matrix["backends"])
    assert "linear" in backends
    assert "github-projects" in backends
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["requiresBackends"] == ["github-projects", "linear"]
    assert set(claim["requiresBackends"]) <= backends
    assert isinstance(claim["adapterComplete"], bool)


def test_r31_browse_contract_fields_without_body_open() -> None:
    """R31 — normative card/list-visible fields per R1 question; body-open is harness failure."""
    contract = ps.operator_projection_contract()
    browse = contract["r1BrowseContract"]
    assert browse["bodyOpenIsFailure"] is True
    for qid in ("1", "2", "3", "4"):
        entry = browse["questions"][qid]
        assert entry["cardVisibleFields"], f"question {qid} missing cardVisibleFields"
        lowered = {str(f).lower() for f in entry["cardVisibleFields"]}
        assert "body" not in lowered
        assert "markdownbody" not in lowered
    result = ps.assert_r1_answerability_from_metadata(
        {
            "1": {"fields": browse["questions"]["1"]["cardVisibleFields"], "bodyOpened": False},
            "2": {"fields": browse["questions"]["2"]["cardVisibleFields"], "bodyOpened": False},
            "3": {"fields": browse["questions"]["3"]["cardVisibleFields"], "bodyOpened": False},
            "4": {"fields": browse["questions"]["4"]["cardVisibleFields"], "bodyOpened": False},
        }
    )
    assert result["verdict"] == "pass"
    bad = ps.assert_r1_answerability_from_metadata(
        {
            "1": {"fields": browse["questions"]["1"]["cardVisibleFields"], "bodyOpened": True},
            "2": {"fields": browse["questions"]["2"]["cardVisibleFields"], "bodyOpened": False},
            "3": {"fields": browse["questions"]["3"]["cardVisibleFields"], "bodyOpened": False},
            "4": {"fields": browse["questions"]["4"]["cardVisibleFields"], "bodyOpened": False},
        }
    )
    assert bad["verdict"] == "fail"
    assert bad["error"] == "r1-body-open"


def test_r32_semantic_status_aliases_fail_closed() -> None:
    """R32 — backlog/in_flight/done via alias allowlist; unknown native fails closed."""
    assert ps.normalize_semantic_status("linear", "In Progress") == "in_flight"
    assert ps.normalize_semantic_status("linear", "Done") == "done"
    assert ps.normalize_semantic_status("linear", "Backlog") == "backlog"
    assert ps.normalize_semantic_status("github-projects", "Todo") == "backlog"
    assert ps.normalize_semantic_status("github-projects", "In Progress") == "in_flight"
    assert ps.normalize_semantic_status("github-projects", "Done") == "done"
    with pytest.raises(ps.SemanticStatusError) as exc:
        ps.normalize_semantic_status("linear", "TotallyUnknownStatusXYZ")
    assert exc.value.code == "unknown-native-status"
    with pytest.raises(ps.SemanticStatusError):
        ps.normalize_semantic_status("github-projects", "WeirdColumn")


def test_r4_projection_mutation_lint_blocks_workflow_bypass(tmp_path: Path) -> None:
    """R4 — workflow import lint fails on direct Linear/Projects mutation helpers."""
    probe = tmp_path / "scripts" / "workflow_bypass_probe.py"
    probe.parent.mkdir(parents=True, exist_ok=True)
    probe.write_text(
        textwrap.dedent(
            """\
            from planning_linear_client import create_issue_batch
            from planning_github_projects_v2 import refresh_projection

            def run():
                refresh_projection(None, {})
            """
        ),
        encoding="utf-8",
    )
    result = ps.lint_projection_mutations(tmp_path, scope=str(probe))
    assert result["verdict"] == "fail"
    assert result["error"] == "projection-mutation-outside-allowlist"
    assert result["violations"]

    facade_ok = ps.lint_projection_mutations(
        Path(scripts).parent,
        scope="scripts/planning_store.py",
    )
    assert facade_ok["verdict"] == "pass"


def test_capability_matrix_includes_live_probe_fields_r18() -> None:
    """R18 — matrix payload includes structural live-probe answerability fields."""
    matrix = ps.operator_projection_capability_matrix()
    assert "linearAnswerable" in matrix
    assert "projectsAnswerable" in matrix
    assert isinstance(matrix["linearAnswerable"], bool)
    assert isinstance(matrix["projectsAnswerable"], bool)


def test_adapter_complete_claim_false_when_not_wired_r18(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(facade, "_linear_live_client_wired", lambda: False)
    monkeypatch.setattr(facade, "_projects_live_client_wired", lambda: False)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is False
    assert claim["answerable"] == {"linear": False, "github-projects": False}


def test_adapter_complete_claim_true_when_both_wired_r18(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(facade, "_linear_live_client_wired", lambda: True)
    monkeypatch.setattr(facade, "_projects_live_client_wired", lambda: True)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is True
    assert claim["answerable"] == {"linear": True, "github-projects": True}


def test_adapter_complete_claim_false_when_only_linear_wired_r18(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(facade, "_linear_live_client_wired", lambda: True)
    monkeypatch.setattr(facade, "_projects_live_client_wired", lambda: False)
    matrix = ps.operator_projection_capability_matrix()
    claim = ps.operator_projection_adapter_complete_claim(matrix)
    assert claim["adapterComplete"] is False


def test_adapter_complete_claim_false_when_live_flag_without_callable_r18(
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
