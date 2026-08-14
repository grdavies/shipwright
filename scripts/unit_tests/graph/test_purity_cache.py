#!/usr/bin/env python3
"""Purity, content-addressed cache, and trust fixtures (PRD 269 R6/R7/R15)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.artifact_registry import (  # noqa: E402
    ArtifactIntegrityError,
    ArtifactRegistry,
    PurityViolationError,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.ir import normalize_node_execution, validate_node_spec  # noqa: E402
from graph.lineage import CacheKeyMaterial, compute_cache_key, keyed_mac  # noqa: E402
from graph.resource_pools import ResourcePoolRegistry  # noqa: E402
from graph.scheduler import GraphScheduler, NodeExecutionResult  # noqa: E402


def _node(
    node_id: str,
    *,
    write_scope: str = "read-only",
    pool: str = "read-only-reviewers",
    execution: dict[str, str] | None = None,
) -> dict[str, object]:
    node: dict[str, object] = {
        "id": node_id,
        "kind": "command",
        "target": {"step": f"sw-{node_id}"},
        "resources": {"pool": pool, "slots": 1, "timeoutSeconds": 300},
        "isolation": {"mode": "process", "writeScope": write_scope},
        "verification": {"required": True, "strategy": "mechanical"},
    }
    if execution is not None:
        node["execution"] = execution
    return node


def test_execution_defaults_and_untrusted_strip() -> None:
    mutating = validate_node_spec(_node("write", write_scope="worktree", pool="code-writers"))
    assert mutating["execution"] == {"purity": "mutating", "cache": "disabled"}

    read_only = validate_node_spec(_node("review"))
    assert read_only["execution"] == {
        "purity": "read-only",
        "cache": "content-addressed",
    }

    stripped = normalize_node_execution(
        _node(
            "evil",
            write_scope="worktree",
            pool="code-writers",
            execution={"purity": "read-only", "cache": "content-addressed"},
        ),
        trusted_template=False,
    )
    assert stripped["execution"] == {"purity": "mutating", "cache": "disabled"}


def test_cache_key_independent_of_run_id() -> None:
    material = CacheKeyMaterial(
        node_definition={"id": "review", "runId": "should-not-matter"},
        input_hashes=["a" * 64],
        prompt_version="p1",
        model_version="m1",
        tool_configuration={"tools": ["pytest"]},
        policy_version="pol1",
        credential_capabilities=["repo:read"],
        scope_identity="proj",
        repository_identity="shipwright",
        trust_domain="in-repo",
        tool_binary_identity="pytest@8",
        repo_state_identity="abc",
    )
    first = compute_cache_key(material)
    second = compute_cache_key(
        CacheKeyMaterial(**{**material.__dict__, "node_definition": {"id": "review"}})
    )
    assert first == second
    assert "should-not-matter" not in first


def test_artifact_mac_and_read_only_write_fail(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    with pytest.raises(PurityViolationError):
        registry.register(
            artifact_id="bad",
            content={"x": 1},
            schema="t",
            producing_node="review",
            input_revision="r1",
            verification_evidence=[],
            purity="read-only",
        )

    record = registry.register(
        artifact_id="ok",
        content={"x": 1},
        schema="t",
        producing_node="build",
        input_revision="r1",
        verification_evidence=["v"],
    )
    assert record.content_mac
    assert registry.read("ok").content == {"x": 1}

    meta = json.loads(registry.metadata_path("ok").read_text(encoding="utf-8"))
    meta["contentMac"] = "0" * 64
    registry.metadata_path("ok").write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ArtifactIntegrityError, match="MAC mismatch"):
        registry.read("ok")


def test_cache_hit_writes_run_scoped_receipt(tmp_path: Path) -> None:
    identity = {
        "prompt_version": "p1",
        "model_version": "fixture",
        "policy_version": "pol1",
        "scope_identity": "s1",
        "repository_identity": "shipwright",
        "trust_domain": "in-repo",
        "tool_binary_identity": "bin1",
        "repo_state_identity": "rev1",
    }
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    pools = ResourcePoolRegistry.from_config(limits={"read-only-reviewers": 2})
    calls: list[str] = []

    def execute(node: dict[str, object]) -> NodeExecutionResult:
        calls.append(str(node["id"]))
        return NodeExecutionResult(
            verdict="pass",
            output={"node": node["id"]},
            model="fixture",
        )

    graph = {
        "apiVersion": "shipwright.dev/v1alpha1",
        "kind": "WorkflowGraph",
        "metadata": {"name": "cache-hit"},
        "spec": {
            "nodes": [_node("review")],
            "edges": [],
            "resourceLimits": {"maxConcurrency": 1, "maxDurationSeconds": 60},
            "verification": {"required": True, "failClosed": True},
        },
    }
    scheduler = GraphScheduler(
        execute,
        receipts=journal,
        pools=pools,
        cache_identity=identity,
    )
    first = scheduler.run(graph, run_id="run-a", internal_only=True)
    second = scheduler.run(graph, run_id="run-b", internal_only=True)

    assert first.verdict == "pass"
    assert second.verdict == "pass"
    assert calls == ["review"]
    assert second.nodes[0].reason == "cache-hit"
    hit = [r for r in second.receipts if r.get("cacheHit") is True]
    assert hit and hit[0]["idempotencyKey"].startswith("run-b:")


def test_failed_receipt_not_reused(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    key = "a" * 64
    payload = {
        "model": "m",
        "attempts": 1,
        "tokens": 1,
        "durationMs": 1,
        "inputHashes": [],
        "outputHashes": ["b" * 64],
        "verdict": "fail",
        "coverage": {},
    }
    journal.record("review", "run-1:hash:review", payload, cache_key=key)
    assert journal.lookup_reusable_by_cache_key(key) is None


def test_mutated_receipt_mac_rejects_cache_reuse(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    key = "c" * 64
    payload = {
        "model": "m",
        "attempts": 1,
        "tokens": 1,
        "durationMs": 1,
        "inputHashes": [],
        "outputHashes": ["d" * 64],
        "verdict": "pass",
        "coverage": {},
    }
    receipt = journal.record("review", "run-1:hash:review", payload, cache_key=key)
    path = journal.complete_path("review", "run-1:hash:review")
    tampered = dict(receipt)
    tampered["outputHashes"] = ["e" * 64]
    path.write_text(json.dumps(tampered) + "\n", encoding="utf-8")
    assert journal.lookup_reusable_by_cache_key(key) is None


def test_keyed_mac_differs_from_unkeyed_sha() -> None:
    payload = b'{"x":1}'
    assert keyed_mac(payload, mac_key=b"k1") != keyed_mac(payload, mac_key=b"k2")
