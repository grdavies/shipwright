"""PRD 091 R2 — replicated planning-cache remote sync failure fixtures."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path
from urllib.error import URLError

import pytest

scripts = Path(__file__).resolve().parents[1]
if str(scripts) not in sys.path:
    sys.path.insert(0, str(scripts))

import planning_authority as pa
import planning_projection_ledger as ppl
import planning_store as ps

RECALLIUM_CFG = {
    "planning": {"store": {"backend": "planning-cache"}},
    "memory": {
        "provider": "recallium",
        "project": "sync-failure-fixture",
        "connection": {"restBaseUrl": "http://localhost:8001"},
    },
}

NO_PROVIDER_CFG = {"planning": {"store": {"backend": "planning-cache"}}}


def _seed_provider_catalog(tmp_root: Path) -> None:
    catalog_src = scripts.parent / ".sw" / "memory-provider-catalog.json"
    if not catalog_src.is_file():
        return
    dest = tmp_root / ".sw" / "memory-provider-catalog.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(catalog_src.read_text(encoding="utf-8"), encoding="utf-8")


def _new_backend(root: Path, cfg: dict) -> ps.ReplicatedPlanningCacheBackend:
    _seed_provider_catalog(root)
    return ps.ReplicatedPlanningCacheBackend(root, cfg)


class UnreachableTransport:
    def urlopen(self, req, timeout: float = 5):  # noqa: ANN001
        raise URLError("connection refused (fixture)")


def _load_doctor():
    return importlib.import_module("planning-doctor")


def test_remote_authority_configured_sync_failure_marks_projection_dirty(tmp_path: Path) -> None:
    original = ps._urlopen
    ps._urlopen = UnreachableTransport().urlopen
    try:
        backend = _new_backend(tmp_path, RECALLIUM_CFG)
        assert pa.has_configured_remote_planning_authority(tmp_path, RECALLIUM_CFG) is True
        put_result = backend.put("unit-sync-fail", "docs/planning/unit-sync-fail/body.md", "sync body")
        assert put_result.verdict == "ok"
        assert put_result.notice is not None
        assert "projection dirty (fail-closed)" in put_result.notice
        assert ppl.projection_is_dirty(tmp_path) is True
        ledger = ppl.load_projection_ledger(tmp_path)
        pending = [event for event in ledger["outbox"] if event["deliveryStatus"] == "pending"]
        assert pending
        assert pending[0]["destination"] == "planning-cache"
        doctor = _load_doctor()
        out = doctor.doctor(tmp_path, sweep=False)
        projection = next(c for c in out["checks"] if c.get("check") == "projection-health")
        assert projection["status"] == "fail"
        assert projection["dirty"] is True
    finally:
        ps._urlopen = original


def test_no_remote_authority_outage_stays_local_only_without_dirty(tmp_path: Path) -> None:
    original = ps._urlopen
    ps._urlopen = UnreachableTransport().urlopen
    try:
        backend = _new_backend(tmp_path, NO_PROVIDER_CFG)
        assert pa.has_configured_remote_planning_authority(tmp_path, NO_PROVIDER_CFG) is False
        put_result = backend.put("unit-local-only", "docs/planning/unit-local-only/body.md", "local body")
        got = backend.get("unit-local-only", "docs/planning/unit-local-only/body.md")
        assert put_result.verdict == "ok"
        assert put_result.notice is not None
        assert "R21a local cache" in put_result.notice
        assert "projection dirty" not in put_result.notice
        assert got.verdict == "ok"
        assert got.content == "local body"
        assert ppl.projection_is_dirty(tmp_path) is False
    finally:
        ps._urlopen = original


def test_record_replicated_cache_sync_failure_is_idempotent(tmp_path: Path) -> None:
    first = ppl.record_replicated_cache_sync_failure(
        tmp_path,
        unit_id="idem-unit",
        operation="put",
        sync_reason="provider-unreachable:URLError",
        body_path="docs/x.md",
    )
    second = ppl.record_replicated_cache_sync_failure(
        tmp_path,
        unit_id="idem-unit",
        operation="put",
        sync_reason="provider-unreachable:URLError",
        body_path="docs/x.md",
    )
    assert first["verdict"] == "fail"
    assert second["verdict"] == "fail"
    ledger = ppl.load_projection_ledger(tmp_path)
    assert len(ledger["outbox"]) == 1
