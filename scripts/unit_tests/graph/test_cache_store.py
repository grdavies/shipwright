#!/usr/bin/env python3
"""Authenticated canonical cache store fixtures (PRD 271 R4–R6, R21–R26)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.cache_store import (  # noqa: E402
    CacheScope,
    CacheStoreFull,
    CanonicalCacheStore,
    cache_identity_eligible,
    node_cache_eligible,
)
from graph.cache_mac import resolve_cache_mac_key  # noqa: E402
from graph.execution_receipts import ExecutionReceiptJournal  # noqa: E402
from graph.lineage import CacheKeyMaterial, compute_stable_cache_key  # noqa: E402


_TEST_MAC = b"test-cache-mac-key-32-bytes-long!!"


def _material() -> CacheKeyMaterial:
    return CacheKeyMaterial(
        node_definition={"id": "node-a", "kind": "command"},
        input_hashes={"in": "abc"},
        prompt_version="p1",
        model_version="m1",
        tool_configuration={},
        policy_version="pol1",
        credential_capability_set=("cap",),
        resolved_scope_identity="scope-1",
        repository_identity="repo-1",
        trust_domain="trust-1",
        tool_binary_identity="tool-1",
        repo_state_identity="state-1",
    )


def _receipt(*, run_id: str = "run-a") -> dict:
    return {
        "state": "complete",
        "nodeId": "node-a",
        "idempotencyKey": f"{run_id}:graph:node-a",
        "model": "fixture",
        "attempts": 1,
        "tokens": 0,
        "durationMs": 1,
        "inputHashes": ["abc"],
        "outputHashes": ["out"],
        "verdict": "pass",
        "coverage": {},
        "receiptHash": "0" * 64,
        "receiptMac": "0" * 64,
    }


def test_cache_identity_rejects_default_wildcard() -> None:
    assert cache_identity_eligible(
        {
            "repo_state_identity": "s",
            "trust_domain": "t",
            "resolved_scope_identity": "scope",
            "repository_identity": "default",
        }
    ) is False
    assert cache_identity_eligible(
        {
            "repo_state_identity": "s",
            "trust_domain": "t",
            "resolved_scope_identity": "scope",
            "repository_identity": "repo",
        }
    ) is True


def test_gate_nodes_are_not_cache_eligible() -> None:
    node = {
        "id": "verify",
        "kind": "verify",
        "execution": {"cache": "content-addressed", "purity": "read-only"},
    }
    identity = {
        "repo_state_identity": "s",
        "trust_domain": "t",
        "resolved_scope_identity": "scope",
        "repository_identity": "repo",
    }
    assert node_cache_eligible(node, identity) is False


def test_mac_required_on_read(tmp_path: Path) -> None:
    store = CanonicalCacheStore(
        tmp_path / "cache",
        scope=CacheScope.RUN,
        repo_root=tmp_path,
        mac_key=_TEST_MAC,
        size_ceiling_bytes=1024 * 1024,
    )
    material = _material()
    key = compute_stable_cache_key(material)
    body = {
        "version": 1,
        "cacheKey": key,
        "stableCacheKey": key,
        "scope": "run",
        "sourceRunId": "run-a",
        "sourceReceipt": _receipt(),
        "artifacts": [],
        "storedAt": 1.0,
    }
    path = store.objects_root / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body), encoding="utf-8")
    assert store.lookup(key, run_id="run-a") is None


def test_put_lookup_run_scope(tmp_path: Path) -> None:
    store = CanonicalCacheStore(
        tmp_path / "cache",
        scope=CacheScope.RUN,
        repo_root=tmp_path,
        mac_key=_TEST_MAC,
    )
    material = _material()
    receipt = _receipt(run_id="run-a")
    receipt["receiptHash"] = "deadbeef"
    receipt["receiptMac"] = "deadbeef"
    # Receipt must be reusable — use journal to stamp integrity
    journal = ExecutionReceiptJournal.for_run(
        tmp_path / "runs",
        "run-a",
        mac_key=_TEST_MAC,
        repo_root=tmp_path,
    )
    stamped = journal.finish("node-a", "run-a:graph:node-a", _receipt(run_id="run-a"))
    key = store.put(
        material=material,
        source_receipt=stamped,
        artifacts=(),
        run_id="run-a",
    )
    hit = store.lookup(key, run_id="run-a")
    assert hit is not None
    assert hit.source == "cache"
    assert hit.original_run_id == "run-a"
    assert store.lookup(key, run_id="run-b") is None


def test_repository_scope_allows_cross_run(tmp_path: Path) -> None:
    store = CanonicalCacheStore(
        tmp_path / "cache",
        scope=CacheScope.REPOSITORY,
        repo_root=tmp_path,
        mac_key=_TEST_MAC,
    )
    journal = ExecutionReceiptJournal.for_run(
        tmp_path / "runs",
        "run-a",
        mac_key=_TEST_MAC,
        repo_root=tmp_path,
    )
    stamped = journal.finish("node-a", "run-a:graph:node-a", _receipt(run_id="run-a"))
    key = store.put(
        material=_material(),
        source_receipt=stamped,
        artifacts=(),
        run_id="run-a",
    )
    assert store.lookup(key, run_id="run-b") is not None


def test_incremental_bookkeeping_and_gc(tmp_path: Path) -> None:
    store = CanonicalCacheStore(
        tmp_path / "cache",
        scope=CacheScope.RUN,
        repo_root=tmp_path,
        mac_key=_TEST_MAC,
        size_ceiling_bytes=1024 * 1024,
    )
    journal = ExecutionReceiptJournal.for_run(
        tmp_path / "runs",
        "run-a",
        mac_key=_TEST_MAC,
        repo_root=tmp_path,
    )
    stamped = journal.finish("node-a", "run-a:graph:node-a", _receipt(run_id="run-a"))
    store.put(
        material=_material(),
        source_receipt=stamped,
        artifacts=({"artifactId": "a1", "schema": "x", "content": {}, "producingNode": "node-a", "inputRevision": "1", "verificationEvidence": []},),
        run_id="run-a",
    )
    stats = json.loads((store.bookkeeping_root / "stats.json").read_text(encoding="utf-8"))
    assert int(stats["entryCount"]) == 1
    assert int(stats["totalBytes"]) > 0
    for path in store.objects_root.glob("*.json"):
        os.utime(path, (1, 1))
    result = store.gc(max_age_seconds=0, now=10.0)
    assert result["deleted"] >= 1


def test_size_ceiling_fail_closed(tmp_path: Path) -> None:
    store = CanonicalCacheStore(
        tmp_path / "cache",
        scope=CacheScope.RUN,
        repo_root=tmp_path,
        mac_key=_TEST_MAC,
        size_ceiling_bytes=64,
    )
    journal = ExecutionReceiptJournal.for_run(
        tmp_path / "runs",
        "run-a",
        mac_key=_TEST_MAC,
        repo_root=tmp_path,
    )
    stamped = journal.finish("node-a", "run-a:graph:node-a", _receipt(run_id="run-a"))
    with pytest.raises(CacheStoreFull):
        store.put(
            material=_material(),
            source_receipt=stamped,
            artifacts=({"artifactId": "a1", "schema": "x", "content": {"big": "x" * 200}, "producingNode": "node-a", "inputRevision": "1", "verificationEvidence": []},),
            run_id="run-a",
        )


def test_receipt_cache_hit_fields(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal.for_run(
        tmp_path / "runs",
        "run-b",
        mac_key=_TEST_MAC,
        repo_root=tmp_path,
    )
    source = journal.finish("node-a", "run-a:graph:node-a", _receipt(run_id="run-a"))
    hit = journal.record_cache_hit(
        "node-a",
        "run-b:graph:node-a",
        source=source,
        cache_key="a" * 64,
        original_run_id="run-a",
    )
    assert hit["cacheHit"] is True
    assert hit["cacheSource"] == "cache"
    assert hit["originalRunId"] == "run-a"


def test_completeness_blocked_on_quarantine(tmp_path: Path) -> None:
    journal = ExecutionReceiptJournal.for_run(
        tmp_path / "runs",
        "run-a",
        mac_key=_TEST_MAC,
        repo_root=tmp_path,
    )
    assert journal.completeness_blocked() is False
    journal.quarantine_root.mkdir(parents=True, exist_ok=True)
    (journal.quarantine_root / "bad.json").write_text("{}", encoding="utf-8")
    assert journal.completeness_blocked() is True


def test_resolve_cache_mac_key_test_override(tmp_path: Path) -> None:
    assert resolve_cache_mac_key(tmp_path, mac_key=_TEST_MAC) == _TEST_MAC
