#!/usr/bin/env python3
"""ExecutionBackend contract and host-authoritative adjudication fixtures (PRD 271 R9/R10)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.execution_backend import (  # noqa: E402
    AdvisoryExecutionReport,
    HostAdjudicationContext,
    InMemoryExecutionBackend,
    KernelAuthorityViolation,
    LocalSyncExecutionBackend,
    PollPhase,
    SubmitRequest,
    TerminalEnvelope,
    adjudicate_terminal_envelope,
    host_cache_identity,
    refuse_kernel_authority_fields,
    strip_kernel_authority_fields,
)
from graph.lineage import CacheKeyMaterial, compute_cache_key  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402


def _submit_request(
    *,
    idempotency_key: str = "run:graph:node-a",
    node_id: str = "node-a",
) -> SubmitRequest:
    from graph.execution_backend import HostExecutionHints

    return SubmitRequest(
        idempotency_key=idempotency_key,
        node={"id": node_id, "kind": "command"},
        capability_token="cap-test",
        input_hashes=("abc123",),
        host_hints=HostExecutionHints(mutating=False, purity="read-only"),
    )


def test_execution_backend_contract() -> None:
    """R9: submit/poll/cancel-ack with durable handles and idempotent submit."""

    def runner(request: SubmitRequest) -> AdvisoryExecutionReport:
        return AdvisoryExecutionReport(
            verdict="pass",
            output={"node": request.node["id"]},
            model="fixture",
            tokens=3,
            duration_ms=99,
        )

    backend = InMemoryExecutionBackend(runner)
    request = _submit_request()

    first = backend.submit(request)
    assert first.duplicate is False
    assert first.handle.handle_id
    assert first.handle.idempotency_key == request.idempotency_key

    second = backend.submit(request)
    assert second.duplicate is True
    assert second.handle.handle_id == first.handle.handle_id

    poll = backend.poll(first.handle)
    assert poll.phase == PollPhase.TERMINAL

    cancel = backend.cancel(first.handle)
    assert cancel.cancel_acknowledged is True
    assert cancel.phase == PollPhase.CANCEL_ACKNOWLEDGED

    terminal = backend.result(first.handle)
    assert terminal.report.verdict == "pass"
    assert terminal.report.output == {"node": "node-a"}


def test_refuses_kernel_authority_fields() -> None:
    """R10: backends cannot authoritatively set kernel-policy fields."""
    payload = {
        "verdict": "pass",
        "output": {"ok": True},
        "scope_identity": "backend-scope",
        "duration_ms": 1,
    }
    with pytest.raises(KernelAuthorityViolation, match="scope_identity"):
        refuse_kernel_authority_fields(payload)

    stripped, violations = strip_kernel_authority_fields(payload)
    assert "scope_identity" in violations
    assert "duration_ms" in violations
    assert stripped == {"verdict": "pass", "output": {"ok": True}}


def test_host_authoritative_identity_purity_timing() -> None:
    """R10: host rejects advisory identity for cache keys; timing/purity host-measured."""

    host_identity = {
        "scope_identity": "host-scope",
        "repository_identity": "host-repo",
        "trust_domain": "host-trust",
        "repo_state_identity": "host-rev",
        "prompt_version": "host-prompt",
        "model_version": "host-model",
        "policy_version": "host-policy",
        "tool_configuration": {"tool": "host"},
        "credential_capabilities": ("host:read",),
    }
    host = HostAdjudicationContext(
        node_id="review",
        idempotency_key="run:graph:review",
        mutating=False,
        purity="read-only",
        cache_identity=host_identity,
        started_at_monotonic=1000.0,
        input_hashes=("deadbeef",),
    )
    advisory = TerminalEnvelope(
        report=AdvisoryExecutionReport(
            verdict="pass",
            output={"x": 1},
            model="backend-model",
            duration_ms=999_999,
            purity="mutating",
            wrote=True,
            scope_identity="backend-scope",
            repository_identity="backend-repo",
            trust_domain="backend-trust",
            repo_state_identity="backend-rev",
            prompt_version="backend-prompt",
            model_version="backend-model-version",
            policy_version="backend-policy",
            tool_configuration={"tool": "backend"},
            credential_capabilities=("backend:write",),
        )
    )

    clock = [1000.0]

    def fake_clock() -> float:
        clock[0] += 0.05
        return clock[0]

    adjudicated = adjudicate_terminal_envelope(host, advisory, clock=fake_clock)
    assert adjudicated.purity == "read-only"
    assert adjudicated.wrote is False
    assert 45 <= adjudicated.duration_ms <= 55
    assert adjudicated.cache_identity["scope_identity"] == "host-scope"
    assert adjudicated.cache_identity["repository_identity"] == "host-repo"
    assert "scope_identity" in adjudicated.advisory_ignored_fields
    assert "duration_ms" in adjudicated.advisory_ignored_fields
    assert "purity" in adjudicated.advisory_ignored_fields

    host_key = compute_cache_key(
        CacheKeyMaterial(
            node_definition={"id": "review"},
            input_hashes={"in": "deadbeef"},
            prompt_version=str(host_identity["prompt_version"]),
            model_version=str(host_identity["model_version"]),
            tool_configuration=dict(host_identity["tool_configuration"]),
            policy_version=str(host_identity["policy_version"]),
            credential_capability_set=tuple(host_identity["credential_capabilities"]),
            resolved_scope_identity=str(host_identity["scope_identity"]),
            repository_identity=str(host_identity["repository_identity"]),
            trust_domain=str(host_identity["trust_domain"]),
            tool_binary_identity="bin",
            repo_state_identity=str(host_identity["repo_state_identity"]),
        )
    )
    advisory_key = compute_cache_key(
        CacheKeyMaterial(
            node_definition={"id": "review"},
            input_hashes={"in": "deadbeef"},
            prompt_version="backend-prompt",
            model_version="backend-model-version",
            tool_configuration={"tool": "backend"},
            policy_version="backend-policy",
            credential_capability_set=("backend:write",),
            resolved_scope_identity="backend-scope",
            repository_identity="backend-repo",
            trust_domain="backend-trust",
            tool_binary_identity="bin",
            repo_state_identity="backend-rev",
        )
    )
    assert host_key != advisory_key
    settled_identity = host_cache_identity(host, result=adjudicated.to_node_execution_result())
    assert settled_identity["scope_identity"] == "host-scope"
    assert compute_cache_key(
        CacheKeyMaterial(
            node_definition={"id": "review"},
            input_hashes={"in": "deadbeef"},
            prompt_version=str(settled_identity["prompt_version"]),
            model_version=str(settled_identity["model_version"]),
            tool_configuration=dict(settled_identity["tool_configuration"]),
            policy_version=str(settled_identity["policy_version"]),
            credential_capability_set=tuple(
                settled_identity.get("credential_capabilities") or ()
            ),
            resolved_scope_identity=str(settled_identity["scope_identity"]),
            repository_identity=str(settled_identity["repository_identity"]),
            trust_domain=str(settled_identity["trust_domain"]),
            tool_binary_identity="bin",
            repo_state_identity=str(settled_identity["repo_state_identity"]),
        )
    ) == host_key


def test_local_sync_backend_via_scheduler(tmp_path: Path) -> None:
    """Scheduler routes node execution through ExecutionBackend without backend authority."""

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        return NodeExecutionResult(
            verdict="pass",
            output={"id": node["id"]},
            model="fixture",
            duration_ms=1,
            scope_identity="executor-scope",
        )

    from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
    from graph.resource_pools import ResourcePoolRegistry  # noqa: E402

    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "backend-wire"},
        "spec": {
            "nodes": [
                {
                    "id": "review",
                    "kind": "command",
                    "target": {"step": "sw-review"},
                    "resources": {
                        "pool": "read-only-reviewers",
                        "slots": 1,
                        "timeoutSeconds": 60,
                    },
                    "isolation": {"mode": "process", "writeScope": "read-only"},
                    "verification": {"required": True, "strategy": "mechanical"},
                }
            ],
            "edges": [],
            "resourceLimits": {"maxConcurrency": 1, "maxDurationSeconds": 60},
            "verification": {"required": True, "failClosed": True},
        },
    }
    scheduler = GraphScheduler(
        execute,
        receipts=ExecutionReceiptJournal(tmp_path / "receipts"),
        pools=ResourcePoolRegistry.from_config(limits={"read-only-reviewers": 1}),
        cache_identity={"scope_identity": "scheduler-scope"},
        backend=LocalSyncExecutionBackend(execute),
    )
    result = scheduler.run(graph, run_id="backend-wire", internal_only=True)
    assert result.verdict == "pass"
    assert result.nodes[0].node_id == "review"
