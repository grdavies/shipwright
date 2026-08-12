#!/usr/bin/env python3
"""Durable artifact-registry and execution-receipt fixtures."""
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
)
from graph.execution_receipts import (  # noqa: E402
    ExecutionReceiptJournal,
    ReceiptConflictError,
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

    with pytest.raises(ArtifactIntegrityError, match="hash mismatch"):
        registry.read("evidence")


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
