"""PRD 333 phase 7 — GitLab planning-store P2 spec stub (R7, R8, R11, R13, R16, R18)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from _planning_pkg_loader import load_backends_package, load_submodule

_backends = load_backends_package()
_pc = load_submodule("provider_conformance")
BACKEND_ID = _backends.GITLAB_PLANNING_STORE_BACKEND_ID
MANDATORY_PLANNING_STORE_VERBS = _pc.MANDATORY_PLANNING_STORE_VERBS
PLANNING_STORE_CORPUS_SCENARIOS = _pc.PLANNING_STORE_CORPUS_SCENARIOS
PLANNING_STORE_MATRIX_VERSION = _pc.PLANNING_STORE_MATRIX_VERSION
PLANNING_STORE_SHIPPED_BACKENDS = _pc.PLANNING_STORE_SHIPPED_BACKENDS
PLANNING_STORE_ALL_BACKENDS = _pc.PLANNING_STORE_ALL_BACKENDS
register_gitlab_planning_store_stub = _backends.register_gitlab_planning_store_stub
gitlab_planning_store_parity_gate = _backends.gitlab_planning_store_parity_gate
GitlabPlanningStoreStubBackend = _backends.GitlabPlanningStoreStubBackend


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _full_capability_claim(*, parity_complete: bool = True, enabled: bool = False) -> dict:
    return {
        "matrixVersion": PLANNING_STORE_MATRIX_VERSION,
        "backend": BACKEND_ID,
        "verbs": {verb: {"verdict": "ok"} for verb in MANDATORY_PLANNING_STORE_VERBS},
        "corpusScenarioIds": sorted(PLANNING_STORE_CORPUS_SCENARIOS),
        "parityComplete": parity_complete,
        "enabled": enabled,
        "shipped": False,
    }


def test_parity_gate_blocks_stub() -> None:
    """R8 — full matrix/corpus claim still refused for P2 stub."""
    claim = _full_capability_claim(parity_complete=True)
    result = gitlab_planning_store_parity_gate(claim)
    assert result["verdict"] == "fail"
    errors = {f["error"] for f in result["failures"]}
    assert "p2-stub-parity-claim-refused" in errors

    partial = {
        "matrixVersion": PLANNING_STORE_MATRIX_VERSION,
        "backend": BACKEND_ID,
        "verbs": {"put": {"verdict": "ok"}},
        "corpusScenarioIds": [],
        "parityComplete": False,
    }
    partial_result = gitlab_planning_store_parity_gate(partial)
    assert partial_result["verdict"] == "fail"
    assert any(f["error"] == "missing-corpus-evidence" for f in partial_result["failures"])


def test_completion_boundary() -> None:
    """R13 — stub is registered but not shipped and reports not-enabled."""
    import planning_store_facade as facade

    registration = register_gitlab_planning_store_stub()
    assert registration["status"] == "not-enabled"
    assert registration["shipped"] is False
    assert registration["parityComplete"] is False
    assert registration["backendId"] == BACKEND_ID
    assert set(registration["mandatoryVerbs"]) == set(MANDATORY_PLANNING_STORE_VERBS)
    assert set(registration["corpusScenarios"]) == PLANNING_STORE_CORPUS_SCENARIOS

    assert BACKEND_ID not in facade.SHIPPED_BACKENDS
    assert BACKEND_ID not in facade.ALL_BACKENDS
    assert BACKEND_ID not in PLANNING_STORE_SHIPPED_BACKENDS
    assert BACKEND_ID not in PLANNING_STORE_ALL_BACKENDS
    assert BACKEND_ID in facade.P2_PLANNING_STORE_STUBS

    root = _repo_root()
    backend = GitlabPlanningStoreStubBackend(root, {"version": 1})
    put_result = backend.put("unit", "docs/planning/sample.md", "body")
    assert put_result.verdict == "deferred"
    assert put_result.reason == "not-enabled"
    assert put_result.inert is True

    footprint = facade.planning_store_p2_stub_registration_footprint()
    assert footprint["verdict"] == "ok"
    stub_entry = footprint["stubs"][BACKEND_ID]
    assert stub_entry["status"] == "not-enabled"
    assert stub_entry["shipped"] is False


def test_stubs_do_not_block_explore_intel() -> None:
    """D3 — GitLab stub does not block follow-on P2/P3 provider programs."""
    import planning_priority_projection as ppp

    doc = ppp.load_authority(_repo_root())
    follow_on = ppp.project_graph_metadata(doc)["providerFollowOn"]
    ids = [item["id"] for item in follow_on]
    assert ids.index("gitlab-planning-store") == 0
    assert "remote-execution" in ids
    assert "upstream-provenance" in ids
    assert "workflow-package-marketplace" in ids

    registration = register_gitlab_planning_store_stub()
    assert registration["status"] == "not-enabled"
    assert registration["programPriorityId"] == "gitlab-planning-store"


@pytest.mark.parametrize("verb", MANDATORY_PLANNING_STORE_VERBS)
def test_stub_verbs_remain_not_enabled(verb: str) -> None:
    """R8/R16 — every mandatory verb returns not-enabled on the stub backend."""
    root = _repo_root()
    backend = GitlabPlanningStoreStubBackend(root, {"version": 1})
    unit_id = "gitlab-stub"
    body_path = "docs/planning/gitlab-stub.md"
    if verb == "put":
        result = backend.put(unit_id, body_path, "sample")
    elif verb == "get":
        result = backend.get(unit_id, body_path)
    elif verb == "exists":
        result = backend.exists(unit_id, body_path)
    elif verb == "materialize":
        result = backend.materialize(unit_id, body_path, root / ".cursor" / "gitlab-stub.md")
    elif verb == "freeze":
        payload = backend.freeze(unit_id, body_path)
        assert payload["verdict"] == "fail"
        assert payload["code"] == "not-enabled"
        return
    else:
        pytest.fail(f"unexpected verb: {verb}")
    assert result.reason == "not-enabled"
    assert result.inert is True


def test_enablement_claim_refused() -> None:
    """R13 — accidental enablement or shipped claims fail closed."""
    claim = _full_capability_claim(parity_complete=False, enabled=True)
    claim["shipped"] = True
    result = gitlab_planning_store_parity_gate(claim)
    assert result["verdict"] == "fail"
    errors = {f["error"] for f in result["failures"]}
    assert "p2-stub-enablement-refused" in errors
    assert "p2-stub-shipped-claim-refused" in errors
