"""Backend adapter round-trip fixtures (PRD 082 phase 12 / R27)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_store as ps
from _planning_pkg_loader import load_backends_package, load_package

planning = load_package()
PlanningStoreBackend = planning.PlanningStoreBackend
backends = load_backends_package()

SAMPLE_CONTENT = "---\nunitId: parity-unit\ntitle: Parity\n---\n\n# Parity body\n"
UNIT_ID = "parity-unit"
BODY_PATH = "docs/planning/parity-unit/body.md"


def _in_repo_cfg() -> dict:
    return {"version": 1, "planning": {"store": {"backend": "in-repo-public"}}}


def _local_synced_cfg(sync_dir: Path) -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "local-synced",
                "localSynced": {"path": str(sync_dir)},
            }
        },
    }


def _memory_cfg() -> dict:
    return {"version": 1, "planning": {"store": {"backend": "memory"}}}


def _assert_generic_contract(backend: PlanningStoreBackend) -> None:
    assert hasattr(backend, "backend_id") and hasattr(backend, "get")
    forbidden = {
        "labels",
        "etag",
        "comments",
        "chunk_manifest",
        "chunk_manifests",
        "issues_provider",
        "_client",
        "_guard_duplicate_open_tasks_mint",
    }
    for name in forbidden:
        assert not hasattr(backend, name), f"provider leakage on generic contract: {name}"


def _round_trip(backend: PlanningStoreBackend, root: Path, dest: Path) -> None:
    _assert_generic_contract(backend)
    put = backend.put(UNIT_ID, BODY_PATH, SAMPLE_CONTENT)
    assert put.verdict == "ok"
    assert put.backend == backend.backend_id
    got = backend.get(UNIT_ID, BODY_PATH)
    assert got.verdict == "ok"
    assert got.content == SAMPLE_CONTENT
    exists = backend.exists(UNIT_ID, BODY_PATH)
    assert exists.verdict == "ok"
    dest.parent.mkdir(parents=True, exist_ok=True)
    mat = backend.materialize(UNIT_ID, BODY_PATH, dest)
    assert mat.verdict == "ok"
    assert dest.read_text(encoding="utf-8") == SAMPLE_CONTENT


def test_in_repo_backend_round_trips(tmp_path: Path) -> None:
    backend = backends.InRepoPublicBackend(tmp_path, _in_repo_cfg())
    _round_trip(backend, tmp_path, tmp_path / ".cursor/materialized/body.md")


def test_local_synced_backend_round_trips(tmp_path: Path) -> None:
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    backend = backends.LocalSyncedBackend(tmp_path, _local_synced_cfg(sync_dir))
    _round_trip(backend, tmp_path, tmp_path / "out/body.md")


def test_memory_backend_round_trips(tmp_path: Path) -> None:
    backend = backends.MemoryLocalCacheBackend(tmp_path, _memory_cfg())
    _round_trip(backend, tmp_path, tmp_path / "out/body.md")


def test_issue_backend_guard_not_on_repository_contract() -> None:
    assert not hasattr(planning.PlanningStoreBackend, "_guard_duplicate_open_tasks_mint")
    assert hasattr(backends.IssueStoreBackend, "_guard_duplicate_open_tasks_mint")


def test_backend_classes_match_planning_store() -> None:
    assert ps.InRepoPublicBackend is backends.InRepoPublicBackend
    assert ps.IssueStoreBackend is backends.IssueStoreBackend
    assert ps.LocalSyncedBackend is backends.LocalSyncedBackend
    assert ps.MemoryLocalCacheBackend is backends.MemoryLocalCacheBackend


def test_get_backend_factory_uses_adapters(tmp_path: Path) -> None:
    cfg = _in_repo_cfg()
    backend = ps.get_backend(tmp_path, cfg)
    assert backend.backend_id == "in-repo-public"
    assert type(backend).__module__.startswith("sw_planning.backends")
