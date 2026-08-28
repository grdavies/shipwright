#!/usr/bin/env python3
"""Remote execution P2 spec stub — trust matrix metadata, fail-closed backend (PRD 333 phase 8)."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from graph.execution_backend import (
    ExecutionBackendError,
    ExecutionHandle,
    PollPhase,
    PollStatus,
    SubmitRequest,
    SubmitResult,
    TerminalEnvelope,
)

BACKEND_ID = "remote"
SPEC_REL_PATH = "core/providers/execution/remote.md"
PROGRAM_PRIORITY_ID = "remote-execution"
TRUST_MATRIX_VERSION = "1.0.0"

MANDATORY_TRUST_DIMENSIONS: tuple[str, ...] = (
    "workload-identity",
    "isolation",
    "least-privilege-credentials",
    "input-output-integrity",
    "idempotency",
    "cancellation",
    "audit-events",
)

NORMALIZED_TRUST_REFUSALS: frozenset[str] = frozenset(
    {
        "identity-mismatch",
        "isolation-failure",
        "over-broad-credentials",
        "integrity-mismatch",
        "idempotency-violation",
        "cancellation-incomplete",
        "missing-audit-evidence",
        "not-enabled",
    }
)

REMOTE_EXECUTION_CORPUS_SCENARIOS: frozenset[str] = frozenset(
    {
        "remote-exec-trust",
        "container-exec-conformance",
        "handoff-continuity",
    }
)

SHIPPED_EXECUTION_BACKENDS: frozenset[str] = frozenset({"local-sync", "container"})
P2_EXECUTION_STUBS: frozenset[str] = frozenset({BACKEND_ID})
ALL_EXECUTION_BACKENDS: frozenset[str] = SHIPPED_EXECUTION_BACKENDS | P2_EXECUTION_STUBS

TRUST_CONFORMANCE_FIXTURES_REL = Path("scripts/test/fixtures/remote-execution-trust")


@dataclass(frozen=True)
class RemoteExecutionConfig:
    credential_ref: str | None = None
    trust_domain: str = "default"
    audit_root: Path | None = None


@dataclass(frozen=True)
class TrustPrerequisiteContext:
    """Inputs for trust-matrix evaluation (hermetic fixtures / enablement tests)."""

    scope_identity: str = "default"
    repository_identity: str = "default"
    trust_domain: str = "default"
    repo_state_identity: str = "default"
    expected_scope_identity: str = "default"
    expected_repository_identity: str = "default"
    expected_trust_domain: str = "default"
    isolation_ok: bool = True
    credential_capabilities: tuple[str, ...] = ()
    allowed_credential_capabilities: tuple[str, ...] = ("graph-remote-exec:read",)
    input_hashes: tuple[str, ...] = ()
    expected_input_hashes: tuple[str, ...] = ()
    output_hash: str | None = None
    expected_output_hash: str | None = None
    idempotency_key: str = "fixture:key"
    prior_handle_id: str | None = None
    duplicate_submit: bool = False
    cancel_requested: bool = False
    cancel_acknowledged: bool = False
    audit_events: tuple[Mapping[str, Any], ...] = ()
    require_audit: bool = True


def remote_execution_capability_matrix() -> dict[str, Any]:
    return {
        "matrixVersion": TRUST_MATRIX_VERSION,
        "backend": BACKEND_ID,
        "dimensions": list(MANDATORY_TRUST_DIMENSIONS),
        "normalizedRefusals": sorted(NORMALIZED_TRUST_REFUSALS),
        "corpusScenarios": sorted(REMOTE_EXECUTION_CORPUS_SCENARIOS),
    }


def register_remote_execution_stub() -> dict[str, Any]:
    """Registration surface for execution_backend — metadata only, not enabled."""
    matrix = remote_execution_capability_matrix()
    return {
        "backendId": BACKEND_ID,
        "status": "not-enabled",
        "shipped": False,
        "trustComplete": False,
        "specPath": SPEC_REL_PATH,
        "programPriorityId": PROGRAM_PRIORITY_ID,
        "trustMatrixVersion": matrix["matrixVersion"],
        "mandatoryDimensions": list(MANDATORY_TRUST_DIMENSIONS),
        "corpusScenarios": sorted(REMOTE_EXECUTION_CORPUS_SCENARIOS),
        "normalizedRefusals": sorted(NORMALIZED_TRUST_REFUSALS),
    }


def evaluate_trust_prerequisites(context: TrustPrerequisiteContext) -> dict[str, Any]:
    """Evaluate one trust context; fail closed on any violated dimension (R9, R11, R17)."""
    failures: list[dict[str, Any]] = []

    if (
        context.scope_identity != context.expected_scope_identity
        or context.repository_identity != context.expected_repository_identity
        or context.trust_domain != context.expected_trust_domain
    ):
        failures.append({"dimension": "workload-identity", "error": "identity-mismatch"})

    if not context.isolation_ok:
        failures.append({"dimension": "isolation", "error": "isolation-failure"})

    extra = set(context.credential_capabilities) - set(context.allowed_credential_capabilities)
    if extra:
        failures.append(
            {
                "dimension": "least-privilege-credentials",
                "error": "over-broad-credentials",
                "observed": sorted(extra),
            }
        )

    if context.input_hashes != context.expected_input_hashes:
        failures.append({"dimension": "input-output-integrity", "error": "integrity-mismatch"})

    if (
        context.expected_output_hash is not None
        and context.output_hash != context.expected_output_hash
    ):
        failures.append({"dimension": "input-output-integrity", "error": "integrity-mismatch"})

    if context.duplicate_submit and context.prior_handle_id is None:
        failures.append({"dimension": "idempotency", "error": "idempotency-violation"})

    if context.cancel_requested and not context.cancel_acknowledged:
        failures.append({"dimension": "cancellation", "error": "cancellation-incomplete"})

    if context.require_audit and not context.audit_events:
        failures.append({"dimension": "audit-events", "error": "missing-audit-evidence"})

    return {
        "verdict": "ok" if not failures else "fail",
        "action": "remote-execution-trust-prerequisites",
        "backend": BACKEND_ID,
        "failures": failures,
    }


def remote_execution_trust_gate(claim: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed on trust or enablement claims for the P2 stub (R9, R13, R17, R18)."""
    failures: list[dict[str, Any]] = []
    backend = str(claim.get("backend") or "")
    if backend != BACKEND_ID:
        failures.append({"field": "backend", "error": "unexpected-backend", "observed": backend})

    matrix_version = str(claim.get("trustMatrixVersion") or "")
    if matrix_version != TRUST_MATRIX_VERSION:
        failures.append(
            {
                "field": "trustMatrixVersion",
                "error": "stale-trust-matrix",
                "observed": matrix_version,
                "expected": TRUST_MATRIX_VERSION,
            }
        )

    dimensions = claim.get("dimensions") or {}
    missing = [dim for dim in MANDATORY_TRUST_DIMENSIONS if dim not in dimensions]
    for dim in missing:
        failures.append({"field": "dimensions", "error": "missing-trust-dimension", "dimension": dim})

    corpus_ids = claim.get("corpusScenarioIds") or claim.get("corpusScenarios") or []
    if not isinstance(corpus_ids, (list, tuple, set)):
        corpus_ids = []
    missing_corpus = sorted(REMOTE_EXECUTION_CORPUS_SCENARIOS - set(corpus_ids))
    for scenario in missing_corpus:
        failures.append(
            {"field": "corpusScenarioIds", "error": "missing-corpus-evidence", "scenario": scenario}
        )

    if claim.get("trustComplete") is True:
        failures.append({"field": "trustComplete", "error": "p2-stub-trust-claim-refused"})
    if claim.get("enabled") is True or claim.get("status") == "enabled":
        failures.append({"field": "status", "error": "p2-stub-enablement-refused"})
    if claim.get("shipped") is True:
        failures.append({"field": "shipped", "error": "p2-stub-shipped-claim-refused"})

    return {
        "verdict": "ok" if not failures else "fail",
        "action": "remote-execution-trust-gate",
        "backend": BACKEND_ID,
        "failures": failures,
    }


def resolve_remote_execution_config(
    cfg: Mapping[str, Any],
    *,
    root: Path | None = None,
) -> RemoteExecutionConfig:
    graph_exec = cfg.get("graphExecution") or {}
    execution = graph_exec.get("execution") or {}
    remote = execution.get("remote") or {}
    audit_raw = remote.get("auditRoot")
    audit_root = Path(audit_raw) if audit_raw else None
    if audit_root is None and root is not None:
        audit_root = root / ".cursor" / "sw-graph-runs" / "remote-audit"
    return RemoteExecutionConfig(
        credential_ref=remote.get("credentialRef"),
        trust_domain=str(remote.get("trustDomain") or "default"),
        audit_root=audit_root,
    )


def remote_execution_default_off(cfg: Mapping[str, Any]) -> bool:
    """True when workflow config does not silently select remote (R17)."""
    graph_exec = cfg.get("graphExecution") or {}
    execution = graph_exec.get("execution") or {}
    backend_kind = str(execution.get("backend") or "local-sync").strip().lower()
    return backend_kind != BACKEND_ID


@dataclass
class RemoteExecutionStubBackend:
    """Present-but-inert remote execution adapter (P2 stub)."""

    config: RemoteExecutionConfig
    root: Path
    gate: Mapping[str, Any] = field(default_factory=dict)

    backend_id: str = BACKEND_ID

    def _not_enabled(self, *, op: str) -> None:
        raise ExecutionBackendError(
            f"remote execution backend refused {op}: not-enabled "
            f"(P2 spec stub — trust prerequisites incomplete)"
        )

    def submit(self, request: SubmitRequest) -> SubmitResult:
        self._not_enabled(op="submit")
        raise AssertionError("unreachable")

    def poll(self, handle: ExecutionHandle) -> PollStatus:
        self._not_enabled(op="poll")
        raise AssertionError("unreachable")

    def cancel(self, handle: ExecutionHandle) -> PollStatus:
        self._not_enabled(op="cancel")
        raise AssertionError("unreachable")

    def result(self, handle: ExecutionHandle) -> TerminalEnvelope:
        self._not_enabled(op="result")
        raise AssertionError("unreachable")


def conformance_metadata_only() -> dict[str, Any]:
    payload = register_remote_execution_stub()
    payload["action"] = "remote-execution-conformance-metadata"
    return payload
