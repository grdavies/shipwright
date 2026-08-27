"""PRD 333 phase 8 — remote execution P2 trust spec stub (R9, R11, R13, R17, R18)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

scripts = Path(__file__).resolve().parents[2]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

from graph.execution_backend import (  # noqa: E402
    ExecutionBackendError,
    HostExecutionHints,
    SubmitRequest,
    create_execution_backend,
    execution_p2_stub_registration_footprint,
)
from graph.remote_execution_backend import (  # noqa: E402
    ALL_EXECUTION_BACKENDS,
    BACKEND_ID,
    MANDATORY_TRUST_DIMENSIONS,
    P2_EXECUTION_STUBS,
    REMOTE_EXECUTION_CORPUS_SCENARIOS,
    SHIPPED_EXECUTION_BACKENDS,
    TRUST_MATRIX_VERSION,
    RemoteExecutionConfig,
    RemoteExecutionStubBackend,
    TrustPrerequisiteContext,
    evaluate_trust_prerequisites,
    register_remote_execution_stub,
    remote_execution_default_off,
    remote_execution_trust_gate,
)
from graph.scheduler import NodeExecutionResult  # noqa: E402


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _valid_context(**overrides: object) -> TrustPrerequisiteContext:
    base = TrustPrerequisiteContext(
        input_hashes=("abc123",),
        expected_input_hashes=("abc123",),
        output_hash="out-hash",
        expected_output_hash="out-hash",
        audit_events=({"phase": "submit", "correlationId": "fixture-1"},),
        require_audit=True,
    )
    if not overrides:
        return base
    data = base.__dict__.copy()
    data.update(overrides)
    return TrustPrerequisiteContext(**data)


def _full_trust_claim(*, trust_complete: bool = True, enabled: bool = False) -> dict:
    return {
        "backend": BACKEND_ID,
        "trustMatrixVersion": TRUST_MATRIX_VERSION,
        "dimensions": {dim: {"verdict": "ok"} for dim in MANDATORY_TRUST_DIMENSIONS},
        "corpusScenarioIds": sorted(REMOTE_EXECUTION_CORPUS_SCENARIOS),
        "trustComplete": trust_complete,
        "enabled": enabled,
        "shipped": False,
    }


def test_trust_gate_blocks_stub_claims() -> None:
    """R13/R18 — full trust/corpus claim still refused for P2 stub."""
    claim = _full_trust_claim(trust_complete=True)
    result = remote_execution_trust_gate(claim)
    assert result["verdict"] == "fail"
    errors = {f["error"] for f in result["failures"]}
    assert "p2-stub-trust-claim-refused" in errors

    partial = {
        "backend": BACKEND_ID,
        "trustMatrixVersion": TRUST_MATRIX_VERSION,
        "dimensions": {"workload-identity": {"verdict": "ok"}},
        "corpusScenarioIds": [],
        "trustComplete": False,
    }
    partial_result = remote_execution_trust_gate(partial)
    assert partial_result["verdict"] == "fail"
    assert any(f["error"] == "missing-corpus-evidence" for f in partial_result["failures"])


def test_completion_boundary() -> None:
    """R13 — stub is registered but not shipped and reports not-enabled."""
    registration = register_remote_execution_stub()
    assert registration["status"] == "not-enabled"
    assert registration["shipped"] is False
    assert registration["trustComplete"] is False
    assert registration["backendId"] == BACKEND_ID
    assert set(registration["mandatoryDimensions"]) == set(MANDATORY_TRUST_DIMENSIONS)
    assert set(registration["corpusScenarios"]) == REMOTE_EXECUTION_CORPUS_SCENARIOS

    assert BACKEND_ID not in SHIPPED_EXECUTION_BACKENDS
    assert BACKEND_ID in P2_EXECUTION_STUBS
    assert BACKEND_ID in ALL_EXECUTION_BACKENDS

    root = _repo_root()
    backend = RemoteExecutionStubBackend(RemoteExecutionConfig(), root)
    with pytest.raises(ExecutionBackendError, match="not-enabled"):
        backend.submit(
            SubmitRequest(
                idempotency_key="stub:key",
                node={"id": "node-a", "kind": "tool"},
                capability_token="",
                input_hashes=("abc",),
                host_hints=HostExecutionHints(mutating=False, purity="read-only"),
            )
        )

    footprint = execution_p2_stub_registration_footprint()
    assert footprint["verdict"] == "ok"
    stub_entry = footprint["stubs"][BACKEND_ID]
    assert stub_entry["status"] == "not-enabled"
    assert stub_entry["shipped"] is False


def test_identity_mismatch_refused() -> None:
    """R9 — workload identity binding must match expected host context."""
    result = evaluate_trust_prerequisites(
        _valid_context(scope_identity="scope-a", expected_scope_identity="scope-b")
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "identity-mismatch" for f in result["failures"])


def test_isolation_failure_refused() -> None:
    """R9 — tenant isolation probe must pass before enablement."""
    result = evaluate_trust_prerequisites(_valid_context(isolation_ok=False))
    assert result["verdict"] == "fail"
    assert any(f["error"] == "isolation-failure" for f in result["failures"])


def test_over_broad_credentials_refused() -> None:
    """R11 — broker scope must refuse capabilities outside the allowlist."""
    result = evaluate_trust_prerequisites(
        _valid_context(
            credential_capabilities=("graph-remote-exec:read", "admin:write"),
            allowed_credential_capabilities=("graph-remote-exec:read",),
        )
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "over-broad-credentials" for f in result["failures"])


def test_integrity_mismatch_refused() -> None:
    """R9 — input/output hashes must match before host adjudication."""
    result = evaluate_trust_prerequisites(
        _valid_context(
            input_hashes=("abc",),
            expected_input_hashes=("def",),
            output_hash="bad",
            expected_output_hash="good",
        )
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "integrity-mismatch" for f in result["failures"])


def test_retry_idempotency_violation_refused() -> None:
    """R9/R17 — duplicate submit without durable prior handle is refused."""
    ok = evaluate_trust_prerequisites(
        _valid_context(duplicate_submit=True, prior_handle_id="handle-1")
    )
    assert ok["verdict"] == "ok"

    bad = evaluate_trust_prerequisites(
        _valid_context(duplicate_submit=True, prior_handle_id=None)
    )
    assert bad["verdict"] == "fail"
    assert any(f["error"] == "idempotency-violation" for f in bad["failures"])


def test_cancellation_incomplete_refused() -> None:
    """R17 — cancel must acknowledge before terminal settlement."""
    result = evaluate_trust_prerequisites(
        _valid_context(cancel_requested=True, cancel_acknowledged=False)
    )
    assert result["verdict"] == "fail"
    assert any(f["error"] == "cancellation-incomplete" for f in result["failures"])


def test_missing_audit_evidence_refused() -> None:
    """R11 — structured audit trail is mandatory for trust claims."""
    result = evaluate_trust_prerequisites(_valid_context(audit_events=()))
    assert result["verdict"] == "fail"
    assert any(f["error"] == "missing-audit-evidence" for f in result["failures"])


def test_enablement_claim_refused() -> None:
    """R13 — accidental enablement or shipped claims fail closed."""
    claim = _full_trust_claim(trust_complete=False, enabled=True)
    claim["shipped"] = True
    result = remote_execution_trust_gate(claim)
    assert result["verdict"] == "fail"
    errors = {f["error"] for f in result["failures"]}
    assert "p2-stub-enablement-refused" in errors
    assert "p2-stub-shipped-claim-refused" in errors


def test_default_off_configuration() -> None:
    """R17 — remote backend is never selected by default."""
    assert remote_execution_default_off({}) is True
    assert remote_execution_default_off({"graphExecution": {"execution": {}}}) is True
    assert (
        remote_execution_default_off(
            {"graphExecution": {"execution": {"backend": "local-sync"}}}
        )
        is True
    )
    assert (
        remote_execution_default_off(
            {"graphExecution": {"execution": {"backend": "remote"}}}
        )
        is False
    )

    root = _repo_root()

    def execute(node: dict) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=node.get("id"))

    default_backend = create_execution_backend(execute, root=root, cfg={})
    assert not isinstance(default_backend, RemoteExecutionStubBackend)

    remote_backend = create_execution_backend(
        execute,
        root=root,
        cfg={"graphExecution": {"execution": {"backend": "remote"}}},
    )
    assert isinstance(remote_backend, RemoteExecutionStubBackend)
    with pytest.raises(ExecutionBackendError, match="not-enabled"):
        remote_backend.submit(
            SubmitRequest(
                idempotency_key="remote:default-off",
                node={"id": "node-b", "kind": "tool"},
                capability_token="",
                input_hashes=("abc",),
                host_hints=HostExecutionHints(mutating=False, purity="read-only"),
            )
        )
