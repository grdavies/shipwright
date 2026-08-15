#!/usr/bin/env python3
"""Durable artifact-registry, schema versioning, and execution-receipt fixtures."""
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
    ArtifactSchemaVersion,
    ProducerNewerThanConsumerError,
    RegisteredSchemaUpgrade,
    SchemaCompatibilityError,
    SchemaUpgradeRegistry,
    canonicalize_schema,
    migrate_legacy_schema,
    parse_schema,
    resolve_schema_for_consumer,
)
from graph.execution_receipts import (  # noqa: E402
    ExecutionReceiptJournal,
    ReceiptConflictError,
)
from graph.lineage import (  # noqa: E402
    CacheKeyMaterial,
    CachedArtifactSnapshot,
    ContentAddressedLineageCache,
    compute_stable_cache_key,
    input_schema_majors_from_schemas,
)


def test_artifact_registry_crud_and_hash_integrity(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    record = registry.register(
        artifact_id="build-output",
        content={"status": "green", "items": [1, 2]},
        schema="shipwright.dev/artifact/build-output/v1",
        producing_node="build",
        input_revision="abc123",
        verification_evidence=["pytest:graph"],
    )

    assert record.artifact_id == "build-output"
    assert record.schema == "shipwright.dev/artifact/build-output@1"
    assert registry.read("build-output").content == {
        "status": "green",
        "items": [1, 2],
    }
    assert registry.list_ids() == ["build-output"]

    registry.delete("build-output")
    with pytest.raises(KeyError):
        registry.read("build-output")


def test_artifact_registry_detects_content_tampering(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    registry.register(
        artifact_id="evidence",
        content="verified",
        schema="text/plain",
        producing_node="verify",
        input_revision="def456",
        verification_evidence=["check:1"],
    )
    registry.content_path("evidence").write_text(
        json.dumps("tampered"), encoding="utf-8"
    )

    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        registry.read("evidence")


def test_legacy_schema_migration_to_canonical_form() -> None:
    assert parse_schema("shipwright.dev/artifact/review/v3") == ArtifactSchemaVersion(
        "shipwright.dev/artifact/review", 3, 0
    )
    assert canonicalize_schema("shipwright.dev/artifact/review/v3") == (
        "shipwright.dev/artifact/review@3"
    )
    assert migrate_legacy_schema("text/plain") == "text/plain@0"


def test_consumer_major_3_refuses_producer_major_2_without_upgrade() -> None:
    upgrades = SchemaUpgradeRegistry()
    with pytest.raises(SchemaCompatibilityError, match="no registered upgrade"):
        resolve_schema_for_consumer(
            producer_schema="review@2",
            consumer_schema="review@3",
            content={"verdict": "pass"},
            upgrades=upgrades,
        )


def test_registered_upgrade_transform_resolves_major_gap() -> None:
    upgrades = SchemaUpgradeRegistry()
    upgrades.register(
        RegisteredSchemaUpgrade(
            schema_name="review",
            from_major=2,
            to_major=3,
            transform=lambda content: {**content, "schemaMajor": 3},
            required_fields=frozenset({"verdict"}),
        )
    )
    resolved, schema = resolve_schema_for_consumer(
        producer_schema="review@2",
        consumer_schema="review@3",
        content={"verdict": "pass"},
        upgrades=upgrades,
    )
    assert schema == "review@3"
    assert resolved["schemaMajor"] == 3


def test_producer_newer_than_consumer_is_fail_closed() -> None:
    with pytest.raises(ProducerNewerThanConsumerError, match="no implicit downgrade"):
        resolve_schema_for_consumer(
            producer_schema="review@3",
            consumer_schema="review@2",
            content={"verdict": "pass"},
            upgrades=SchemaUpgradeRegistry(),
        )


def test_cache_hit_misses_across_major_bump(tmp_path: Path) -> None:
    registry = ArtifactRegistry(tmp_path / "artifacts")
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    cache = ContentAddressedLineageCache(
        tmp_path / "lineage",
        registry=registry,
        journal=journal,
    )

    def _material(**schema_majors: str) -> CacheKeyMaterial:
        return CacheKeyMaterial(
            node_definition={"id": "verify", "kind": "command"},
            input_hashes={"prompt": "a" * 64},
            prompt_version="prompt-v1",
            model_version="build-v1",
            tool_configuration={"tools": ["read"]},
            policy_version="policy-v1",
            credential_capability_set=("github.read",),
            resolved_scope_identity="scope-1",
            repository_identity="repo-1",
            trust_domain="shipwright.dev",
            tool_binary_identity="python3.12",
            repo_state_identity="deadbeef",
            input_schema_majors=input_schema_majors_from_schemas(
                {"prompt": schema for schema in schema_majors.values()}
            )
            if schema_majors
            else {"prompt": "review@2"},
        )

    material_v2 = _material(prompt="review@2")
    material_v3 = _material(prompt="review@3")
    assert compute_stable_cache_key(material_v2) != compute_stable_cache_key(material_v3)

    journal.begin("verify", "source-run:verify", _receipt())
    source_receipt = journal.complete("verify", "source-run:verify", verdict="pass")
    registry.register(
        artifact_id="review-output",
        content={"verdict": "pass"},
        schema="review@2",
        producing_node="verify",
        input_revision="rev-1",
        verification_evidence=["pytest"],
    )
    snapshot = CachedArtifactSnapshot.from_record(registry.read("review-output"))
    cache.store_success(
        material=material_v2,
        source_receipt=source_receipt,
        artifacts=[snapshot],
    )
    registry.delete("review-output")

    hit = cache.try_cache_hit(
        run_id="run-2",
        node_id="verify",
        material=material_v3,
        receipt_payload=_receipt(),
    )
    assert hit is None


def test_exact_digest_approval_remains_execution_authority(tmp_path: Path) -> None:
    """Content hash/MAC remain execution authority after schema resolution."""
    registry = ArtifactRegistry(tmp_path / "artifacts")
    upgrades = SchemaUpgradeRegistry()
    upgrades.register(
        RegisteredSchemaUpgrade(
            schema_name="review",
            from_major=2,
            to_major=3,
            transform=lambda content: {**content, "schemaMajor": 3},
            required_fields=frozenset({"verdict"}),
        )
    )
    resolved, schema = resolve_schema_for_consumer(
        producer_schema="review@2",
        consumer_schema="review@3",
        content={"verdict": "pass"},
        upgrades=upgrades,
    )
    record = registry.register(
        artifact_id="review-output",
        content=resolved,
        schema=schema,
        producing_node="verify",
        input_revision="rev-1",
        verification_evidence=["digest"],
    )
    assert record.content_hash == registry.fingerprint("review-output")

    registry.content_path("review-output").write_text(
        json.dumps({**resolved, "verdict": "fail"}), encoding="utf-8"
    )
    with pytest.raises(ArtifactIntegrityError, match="mismatch"):
        registry.read("review-output")


def _receipt(verdict: str = "pass") -> dict[str, object]:
    return {
        "model": "build-model",
        "attempts": 1,
        "tokens": {"input": 120, "output": 30},
        "durationMs": 250,
        "inputHashes": {"prompt": "a" * 64},
        "outputHashes": {"result": "b" * 64},
        "verdict": verdict,
        "coverage": {"required": 4, "completed": 4},
    }


def test_receipt_writes_are_idempotent(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal(tmp_path / "receipts")

    first = journal.record("verify", "run-1:verify", _receipt())
    repeated = journal.record("verify", "run-1:verify", _receipt())

    assert first == repeated
    assert len(journal.list_receipts()) == 1
    with pytest.raises(ReceiptConflictError):
        journal.record("verify", "run-1:verify", _receipt("fail"))


def test_partial_receipt_is_resumable_and_corruption_is_quarantined(
    tmp_path: Path,
) -> None:
    journal = ExecutionReceiptJournal(tmp_path / "receipts")
    partial = journal.begin("build", "run-1:build", _receipt())

    assert partial["state"] == "partial"
    assert journal.resume_partial("build", "run-1:build")["state"] == "partial"

    completed = journal.complete("build", "run-1:build", verdict="pass")
    assert completed["state"] == "complete"
    assert journal.get("build", "run-1:build") == completed

    corrupt = journal.begin("test", "run-1:test", _receipt())
    assert corrupt["state"] == "partial"
    journal.partial_path("test", "run-1:test").write_text("{", encoding="utf-8")
    with pytest.raises(ReceiptConflictError, match="quarantined"):
        journal.resume_partial("test", "run-1:test")
    assert list((tmp_path / "receipts" / "quarantine").iterdir())
