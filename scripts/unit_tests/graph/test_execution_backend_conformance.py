#!/usr/bin/env python3
"""Parameterized ExecutionBackend conformance suite (PRD 279 R6)."""
from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.container_execution_backend import (  # noqa: E402
    ContainerExecutionBackend,
    ContainerExecutionConfig,
    ContainerHandleStore,
    MockContainerRuntime,
)
from graph.execution_backend import (  # noqa: E402
    ExecutionBackend,
    ExecutionBackendError,
    HostExecutionHints,
    InMemoryExecutionBackend,
    LocalSyncExecutionBackend,
    PollPhase,
    SubmitRequest,
    TerminalEnvelope,
    AdvisoryExecutionReport,
)
from graph.lineage import CacheKeyMaterial, compute_cache_key  # noqa: E402
from graph.scheduler import NodeExecutionResult  # noqa: E402

_FIXTURES = Path(__file__).resolve().parents[2] / "test" / "fixtures" / "graph-backend"
_NODE = json.loads((_FIXTURES / "conformance-node.json").read_text(encoding="utf-8"))
_READ_NODE = dict(_NODE["node"])
_MUTATING_NODE = dict(_NODE["mutatingNode"])

BackendFactory = Callable[[Path], ExecutionBackend]


def _submit_request(
    *,
    idempotency_key: str = "conformance:node-a",
    node: Mapping[str, Any] | None = None,
    mutating: bool = False,
    capability_token: str = "",
) -> SubmitRequest:
    target = dict(node or _READ_NODE)
    return SubmitRequest(
        idempotency_key=idempotency_key,
        node=target,
        capability_token=capability_token,
        input_hashes=("abc123",),
        host_hints=HostExecutionHints(
            mutating=mutating,
            purity="mutating" if mutating else "read-only",
        ),
    )


def _local_sync_factory(tmp_path: Path) -> ExecutionBackend:
    def execute(node: dict[str, Any]) -> NodeExecutionResult:
        return NodeExecutionResult(
            verdict="pass",
            output={"nodeId": node.get("id")},
            model="local-sync-fixture",
        )

    return LocalSyncExecutionBackend(execute)


def _in_memory_factory(tmp_path: Path) -> ExecutionBackend:
    def runner(request: SubmitRequest) -> AdvisoryExecutionReport:
        return AdvisoryExecutionReport(
            verdict="pass",
            output={"nodeId": request.node.get("id")},
            model="in-memory-fixture",
        )

    return InMemoryExecutionBackend(runner)


def _container_factory(tmp_path: Path) -> ExecutionBackend:
    config = ContainerExecutionConfig(store_root=tmp_path / "container-handles")
    return ContainerExecutionBackend(
        config=config,
        runtime=MockContainerRuntime(delay_s=0.01),
        store=ContainerHandleStore(config.store_root),
        root=tmp_path,
        credential_resolver=lambda _ref, _root: {"GRAPH_CONTAINER_TOKEN": "fixture-token"},
    )


BACKEND_FACTORIES: list[tuple[str, BackendFactory]] = [
    ("local-sync", _local_sync_factory),
    ("in-memory", _in_memory_factory),
    ("container", _container_factory),
]


@pytest.fixture(params=[name for name, _ in BACKEND_FACTORIES], ids=[name for name, _ in BACKEND_FACTORIES])
def backend_factory(request: pytest.FixtureRequest) -> tuple[str, BackendFactory]:
    name = str(request.param)
    factory = dict(BACKEND_FACTORIES)[name]
    return name, factory


@pytest.fixture
def backend(
    tmp_path: Path,
    backend_factory: tuple[str, BackendFactory],
) -> ExecutionBackend:
    _, factory = backend_factory
    return factory(tmp_path)


def test_submission_idempotency(backend: ExecutionBackend) -> None:
    """R4: duplicate idempotency_key returns the same handle."""
    request = _submit_request(idempotency_key="conformance:idempotent")
    first = backend.submit(request)
    second = backend.submit(request)
    assert first.handle.handle_id
    assert second.duplicate is True
    assert second.handle.handle_id == first.handle.handle_id


def test_poll_reaches_terminal(backend: ExecutionBackend) -> None:
    """R5: poll advances to terminal settlement."""
    submit = backend.submit(_submit_request(idempotency_key="conformance:poll"))
    handle = submit.handle
    poll = backend.poll(handle)
    deadline = time.monotonic() + 5.0
    while poll.phase not in (PollPhase.TERMINAL, PollPhase.CANCEL_ACKNOWLEDGED):
        assert time.monotonic() < deadline
        poll = backend.poll(handle)
    terminal = backend.result(handle)
    assert terminal.report.verdict in {"pass", "cancelled", "fail"}


def test_cancel_ack_before_terminal(backend_factory: tuple[str, BackendFactory], tmp_path: Path) -> None:
    """R5: cancel surfaces cancel-acknowledged before terminal result (async backends)."""
    name, factory = backend_factory
    if name != "container":
        pytest.skip("cancel-ack semantics require async backend lifecycle")
    backend = factory(tmp_path)
    submit = backend.submit(_submit_request(idempotency_key="conformance:cancel"))
    handle = submit.handle
    cancel = backend.cancel(handle)
    assert cancel.cancel_acknowledged is True
    assert cancel.phase == PollPhase.CANCEL_ACKNOWLEDGED
    terminal = backend.result(handle)
    assert terminal.report.verdict == "cancelled"


def test_handle_identity_validation(backend: ExecutionBackend) -> None:
    """R6: mismatched idempotency_key is refused."""
    submit = backend.submit(_submit_request(idempotency_key="conformance:identity"))
    bad_handle = type(submit.handle)(submit.handle.handle_id, "wrong-key")
    with pytest.raises(ExecutionBackendError, match="mismatch|unknown"):
        backend.poll(bad_handle)


def test_receipt_durability_container(tmp_path: Path) -> None:
    """R6: container handles survive store reload (crash recovery)."""
    config = ContainerExecutionConfig(store_root=tmp_path / "durable-handles")
    store = ContainerHandleStore(config.store_root)
    backend = ContainerExecutionBackend(
        config=config,
        runtime=MockContainerRuntime(delay_s=0.0),
        store=store,
        root=tmp_path,
    )
    submit = backend.submit(_submit_request(idempotency_key="conformance:durable"))
    reloaded = ContainerExecutionBackend(
        config=config,
        runtime=MockContainerRuntime(delay_s=0.0),
        store=ContainerHandleStore(config.store_root),
        root=tmp_path,
    )
    poll = reloaded.poll(submit.handle)
    while poll.phase not in (PollPhase.TERMINAL, PollPhase.CANCEL_ACKNOWLEDGED):
        poll = reloaded.poll(submit.handle)
    terminal = reloaded.result(submit.handle)
    assert terminal.report.verdict in {"pass", "fail"}


def test_generation_fence_refuses_stale_mutation(tmp_path: Path) -> None:
    """R6: stale generation refuses handle mutation."""
    config = ContainerExecutionConfig(store_root=tmp_path / "fence-handles")
    store = ContainerHandleStore(config.store_root)
    backend = ContainerExecutionBackend(
        config=config,
        runtime=MockContainerRuntime(),
        store=store,
        root=tmp_path,
    )
    submit = backend.submit(_submit_request(idempotency_key="conformance:fence"))
    record = store.get(submit.handle.handle_id)
    assert record is not None
    with pytest.raises(ExecutionBackendError, match="generation fence"):
        store.mutate(
            record.handle_id,
            generation=record.generation + 99,
            mutator=lambda _h: None,
        )


def test_mutating_refused_without_capability_token(tmp_path: Path) -> None:
    """R7: mutating container nodes require capability_token."""
    config = ContainerExecutionConfig(
        store_root=tmp_path / "mutating-handles",
        credential_ref="fixture/container-exec",
    )
    backend = ContainerExecutionBackend(
        config=config,
        runtime=MockContainerRuntime(),
        store=ContainerHandleStore(config.store_root),
        root=tmp_path,
        credential_resolver=lambda _ref, _root: {"GRAPH_CONTAINER_TOKEN": "fixture-token"},
    )
    request = _submit_request(
        idempotency_key="conformance:mutating-gate",
        node=_MUTATING_NODE,
        mutating=True,
        capability_token="",
    )
    with pytest.raises(ExecutionBackendError, match="capability_token"):
        backend.submit(request)


def test_cache_identity_stability() -> None:
    """R6: cache key material is stable for identical inputs."""
    material_a = CacheKeyMaterial(
        node_definition={"id": "node-a"},
        input_hashes={"in": "hash-1"},
        prompt_version="v1",
        model_version="m1",
        tool_configuration={"tool": "fixture"},
        policy_version="p1",
        credential_capability_set=("read",),
        resolved_scope_identity="scope",
        repository_identity="repo",
        trust_domain="trust",
        tool_binary_identity="tool-bin",
        repo_state_identity="rev",
    )
    material_b = CacheKeyMaterial(
        node_definition={"id": "node-a"},
        input_hashes={"in": "hash-1"},
        prompt_version="v1",
        model_version="m1",
        tool_configuration={"tool": "fixture"},
        policy_version="p1",
        credential_capability_set=("read",),
        resolved_scope_identity="scope",
        repository_identity="repo",
        trust_domain="trust",
        tool_binary_identity="tool-bin",
        repo_state_identity="rev",
    )
    assert compute_cache_key(material_a) == compute_cache_key(material_b)


def test_create_execution_backend_defaults_local_sync(tmp_path: Path) -> None:
    """R1: factory defaults to LocalSync when backend unset."""
    from graph.execution_backend import create_execution_backend

    def execute(node: dict[str, Any]) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=node.get("id"))

    backend = create_execution_backend(execute, root=tmp_path, cfg={})
    submit = backend.submit(_submit_request(idempotency_key="conformance:factory-default"))
    terminal = backend.result(submit.handle)
    assert terminal.report.verdict == "pass"


def test_create_execution_backend_selects_container(tmp_path: Path) -> None:
    """R3: factory selects container backend when configured."""
    from graph.execution_backend import create_execution_backend

    cfg = {
        "graphExecution": {
            "execution": {
                "backend": "container",
                "container": {"storeRoot": str(tmp_path / "factory-handles")},
            }
        }
    }

    def execute(node: dict[str, Any]) -> NodeExecutionResult:
        return NodeExecutionResult(verdict="pass", output=node.get("id"))

    backend = create_execution_backend(
        execute,
        root=tmp_path,
        cfg=cfg,
        runtime=MockContainerRuntime(delay_s=0.0),
        credential_resolver=lambda _ref, _root: {"GRAPH_CONTAINER_TOKEN": "fixture-token"},
    )
    submit = backend.submit(_submit_request(idempotency_key="conformance:factory-container"))
    poll = backend.poll(submit.handle)
    while poll.phase not in (PollPhase.TERMINAL, PollPhase.CANCEL_ACKNOWLEDGED):
        poll = backend.poll(submit.handle)
    assert backend.result(submit.handle).report.verdict == "pass"
