#!/usr/bin/env python3
"""Purity, cache-key lineage, and trust fixtures (PRD 269 R6/R7/R15)."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.artifact_registry import (  # noqa: E402
    ArtifactIntegrityError,
    ArtifactRegistry,
    PurityViolationError,
    receipt_satisfies_cache_hit,
)
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.ir import (  # noqa: E402
    WorkflowGraphValidationError,
    normalize_node_execution,
    validate_node_spec,
)
from graph.lineage import (  # noqa: E402
    CacheKeyMaterial,
    CachedArtifactSnapshot,
    ContentAddressedLineageCache,
    LineageError,
    compute_cache_key,
    compute_stable_cache_key,
    receipt_is_cache_reusable,
)


def _node(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": "verify",
        "kind": "command",
        "target": {"step": "sw-verify"},
        "resources": {
            "pool": "read-only-reviewers",
            "slots": 1,
            "timeoutSeconds": 120,
        },
        "isolation": {"mode": "process", "writeScope": "read-only"},
        "verification": {"required": True, "strategy": "mechanical"},
    }
    base.update(overrides)
    return base


def _material(**overrides: object) -> CacheKeyMaterial:
    defaults = {
        "node_definition": {"id": "verify", "kind": "command"},
        "input_hashes": {"prompt": "a" * 64},
        "prompt_version": "prompt-v1",
        "model_version": "build-v1",
        "tool_configuration": {"tools": ["read"]},
        "policy_version": "policy-v1",
        "credential_capability_set": ("github.read",),
        "resolved_scope_identity": "scope-1",
        "repository_identity": "repo-1",
        "trust_domain": "shipwright.dev",
        "tool_binary_identity": "python3.12",
        "repo_state_identity": "deadbeef",
    }
    defaults.update(overrides)
    return CacheKeyMaterial(**defaults)


def _receipt_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "model": "build-model",
        "attempts": 1,
        "tokens": {"input": 10, "output": 5},
        "durationMs": 100,
        "inputHashes": {"prompt": "a" * 64},
        "outputHashes": {"result": "b" * 64},
        "verdict": "pass",
        "coverage": {"required": 1, "completed": 1},
    }
    payload.update(overrides)
    return payload


def _complete_receipt(journal: ExecutionReceiptJournal, node_id: str, key: str) -> dict:
    journal.begin(node_id, key, _receipt_payload())
    return journal.complete(node_id, key, verdict="pass")


def test_execution_defaults_from_isolation_write_scope() -> None:
    read_only = normalize_node_execution(_node())
    assert read_only["execution"] == {
        "purity": "read-only",
        "cache": "content-addressed",
    }

    mutating = normalize_node_execution(
        _node(
            id="execute",
            isolation={"mode": "worktree", "writeScope": "worktree"},
            resources={"pool": "code-writers", "slots": 1, "timeoutSeconds": 300},
        )
    )
    assert mutating["execution"] == {"purity": "mutating", "cache": "disabled"}


def test_mutating_nodes_reject_content_addressed_cache() -> None:
    with pytest.raises(WorkflowGraphValidationError, match="cache disabled"):
        validate_node_spec(
            _node(
                id="execute",
                isolation={"mode": "worktree", "writeScope": "worktree"},
                execution={"purity": "mutating", "cache": "content-addressed"},
            )
        )


def test_trust_fields_require_template_digest() -> None:
    with pytest.raises(WorkflowGraphValidationError, match="templateDigest"):
        validate_node_spec(
            _node(
                execution={
                    "purity": "read-only",
                    "cache": "content-addressed",
                    "trust": {"trustDomain": "shipwright.dev"},
                }
            )
        )


def test_untrusted_payload_strips_execution_overrides() -> None:
    node = _node(
        execution={"purity": "mutating", "cache": "content-addressed"},
    )
    normalized = normalize_node_execution(node, trusted_template=False)
    assert normalized["execution"] == {
        "purity": "read-only",
        "cache": "content-addressed",
    }


def test_cache_key_is_independent_of_run_id() -> None:
    material = _material(
        node_definition={"id": "verify", "kind": "command", "runId": "run-a"}
    )
    other = _material(
        node_definition={"id": "verify", "kind": "command", "runId": "run-b"}
    )
    assert compute_stable_cache_key(material) == compute_stable_cache_key(other)
    assert compute_cache_key(material) == compute_stable_cache_key(material)


def test_cache_key_changes_when_inputs_change() -> None:
    left = _material(input_hashes={"prompt": "a" * 64})
    right = _material(input_hashes={"prompt": "b" * 64})
    assert compute_stable_cache_key(left) != compute_stable_cache_key(right)


def test_read_only_registry_write_fails_closed(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    with pytest.raises(PurityViolationError, match="read-only"):
        registry.register(
            artifact_id="review-output",
            content={"ok": True},
            schema="shipwright.dev/artifact/review/v1",
            producing_node="verify",
            input_revision="rev-1",
            verification_evidence=["pytest"],
            purity="read-only",
        )


def test_receipt_satisfies_cache_hit_rejects_failed_retry_and_mutated() -> None:
    journal = ExecutionReceiptJournal(Path("/tmp/unused-receipts"))
    complete = _complete_receipt(journal, "verify", "stable-key")
    assert receipt_satisfies_cache_hit(complete) is True
    assert receipt_is_cache_reusable(complete) is True

    failed = deepcopy(complete)
    failed["verdict"] = "fail"
    assert receipt_satisfies_cache_hit(failed) is False

    retry = deepcopy(complete)
    retry["retryOnly"] = True
    assert receipt_satisfies_cache_hit(retry) is False

    mutated = deepcopy(complete)
    mutated["receiptMutated"] = True
    assert receipt_satisfies_cache_hit(mutated) is False


def test_content_addressed_cache_hit_restores_artifacts_and_writes_receipt(
    tmp_path: Path,
) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    cache = ContentAddressedLineageCache(
        tmp_path / "lineage",
        registry=registry,
        journal=journal,
    )
    material = _material()
    source_receipt = _complete_receipt(journal, "verify", "source-run:verify")
    registry.register(
        artifact_id="review-output",
        content={"verdict": "pass"},
        schema="shipwright.dev/artifact/review/v1",
        producing_node="verify",
        input_revision="rev-1",
        verification_evidence=["pytest"],
    )
    snapshot = CachedArtifactSnapshot.from_record(registry.read("review-output"))
    stable_key = cache.store_success(
        material=material,
        source_receipt=source_receipt,
        artifacts=[snapshot],
    )
    registry.delete("review-output")
    assert "review-output" not in registry.list_ids()

    hit = cache.try_cache_hit(
        run_id="run-2",
        node_id="verify",
        material=material,
        receipt_payload=_receipt_payload(),
    )
    assert hit is not None
    assert hit["cacheHit"] is True
    assert hit["stableCacheKey"] == stable_key
    assert registry.read("review-output").content == {"verdict": "pass"}


def test_failed_source_receipt_is_never_reused(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    cache = ContentAddressedLineageCache(
        tmp_path / "lineage",
        registry=ArtifactRegistry(tmp_path / "artifacts"),
        journal=journal,
    )
    material = _material()
    failed = _complete_receipt(journal, "verify", "failed-key")
    failed["verdict"] = "fail"
    with pytest.raises(LineageError, match="not cache-reusable"):
        cache.store_success(material=material, source_receipt=failed, artifacts=[])


def test_artifact_registry_uses_keyed_mac_not_sha256_alone(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    registry.register(
        artifact_id="output",
        content={"value": 1},
        schema="shipwright.dev/artifact/output/v1",
        producing_node="build",
        input_revision="rev-1",
        verification_evidence=["pytest"],
    )
    metadata = json.loads(registry.metadata_path("output").read_text(encoding="utf-8"))
    assert "contentMac" in metadata
    assert metadata["contentMac"] != metadata["contentHash"]
    registry.content_path("output").write_text(
        json.dumps({"value": 2}), encoding="utf-8"
    )
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        registry.read("output")
