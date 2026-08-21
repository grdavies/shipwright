#!/usr/bin/env python3
"""PRD 279 R9–R11 — RunOwnershipProvider CAS leases and generation fencing."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from graph.run_ownership import (  # noqa: E402
    DeliverRunOwnershipProvider,
    RunOwnershipLeaseRecord,
)
from wave_lock import RUN_LEASE_STALE_SECONDS, run_lease_path_for  # noqa: E402


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _stale_timestamp() -> str:
    past = datetime.now(timezone.utc) - timedelta(seconds=RUN_LEASE_STALE_SECONDS + 60)
    return past.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_acquire_returns_generation_and_fencing_token(repo: Path) -> None:
    """R9 — acquire returns generation + fencingToken lease record."""
    provider = DeliverRunOwnershipProvider(repo)
    out = provider.acquire("deliver-run-ownership-test")
    assert out["verdict"] == "pass"
    assert out["generation"] == 1
    lease = out["lease"]
    assert lease["runId"] == "deliver-run-ownership-test"
    assert lease["generation"] == 1
    assert lease["fencingToken"] == "deliver-run-ownership-test:1"


def test_stale_reclaim_bumps_generation(repo: Path) -> None:
    """R10/R11 — stale heartbeat + dead PID reclaims and bumps generation."""
    provider = DeliverRunOwnershipProvider(repo)
    first = provider.acquire("deliver-reclaim")
    assert first["verdict"] == "pass"

    lock_path = run_lease_path_for(repo, "deliver-reclaim")
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 424242
    meta["heartbeatAt"] = _stale_timestamp()
    meta["acquiredAt"] = meta["heartbeatAt"]
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    with patch("wave_lock.ship_lease_pid_alive", return_value=False):
        second = provider.acquire("deliver-reclaim")

    assert second["verdict"] == "pass"
    assert second.get("reclaimed") is True
    assert second["generation"] == 2
    assert second["lease"]["fencingToken"] == "deliver-reclaim:2"


def test_generation_fencing_refuses_stale_write(repo: Path) -> None:
    """R11 — prior generation writes fail closed after reclaim."""
    provider = DeliverRunOwnershipProvider(repo)
    first = provider.acquire("deliver-fence")
    prior_gen = int(first["generation"])

    lock_path = run_lease_path_for(repo, "deliver-fence")
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 515151
    meta["heartbeatAt"] = _stale_timestamp()
    meta["acquiredAt"] = meta["heartbeatAt"]
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    with patch("wave_lock.ship_lease_pid_alive", return_value=False):
        second = provider.acquire("deliver-fence")

    assert second["verdict"] == "pass"
    denied = provider.assert_write("deliver-fence", prior_gen)
    assert denied["verdict"] == "fail"
    assert denied["error"] == "run-lease-generation-stale"

    allowed = provider.assert_write("deliver-fence", int(second["generation"]))
    assert allowed["verdict"] == "pass"


def test_cross_host_acquire_fail_closed_without_ack(repo: Path) -> None:
    """R10 — foreign host lease blocks acquire without cross-host ack."""
    provider = DeliverRunOwnershipProvider(repo)
    lock_path = run_lease_path_for(repo, "deliver-cross-host")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "kind": "deliver-run-lease",
        "runId": "deliver-cross-host",
        "generation": 1,
        "owner": "other-host:1",
        "host": "other-host",
        "pid": 1,
        "acquiredAt": "2000-01-01T00:00:00Z",
        "heartbeatAt": "2000-01-01T00:00:00Z",
    }
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    blocked = provider.acquire("deliver-cross-host")
    assert blocked["verdict"] == "fail"
    assert blocked["error"] in ("run-lease-cross-host", "run-lease-held")
    assert blocked.get("halt")


def test_lease_record_from_lock_meta_expiry(repo: Path) -> None:
    """R12 — lease record exposes expiry derived from heartbeat TTL."""
    hb = "2026-01-01T00:00:00Z"
    record = RunOwnershipLeaseRecord.from_lock_meta(
        {
            "runId": "x",
            "owner": "host:1",
            "generation": 3,
            "heartbeatAt": hb,
        }
    )
    assert record.fencing_token == "x:3"
    assert record.expiry.endswith("Z")
