"""PRD 276 R11/R20 — stale reclaim + monotonic generation fencing."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_lock import (
    acquire_run_lease,
    assert_run_lease_write,
    run_lease_path_for,
    RUN_LEASE_STALE_SECONDS,
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _stale_timestamp() -> str:
    past = datetime.now(timezone.utc) - timedelta(seconds=RUN_LEASE_STALE_SECONDS + 60)
    return past.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_stale_lease_reclaim_after_ttl(repo: Path) -> None:
    """R11 — stale leases reclaimable after TTL/heartbeat miss without surgery."""
    run_id = "deliver-stale-reclaim"
    first = acquire_run_lease(repo, run_id)
    assert first["verdict"] == "pass"
    assert first["generation"] == 1

    lock_path = run_lease_path_for(repo, run_id)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 999001
    meta["heartbeatAt"] = _stale_timestamp()
    meta["acquiredAt"] = meta["heartbeatAt"]
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    with patch("wave_lock.ship_lease_pid_alive", return_value=False):
        second = acquire_run_lease(repo, run_id)

    assert second["verdict"] == "pass"
    assert second.get("reclaimed") is True
    assert second["generation"] == 2
    held = json.loads(lock_path.read_text(encoding="utf-8"))
    assert held["generation"] == 2
    assert held["pid"] == os.getpid()


def test_lease_generation_fencing_stale_write_refused(repo: Path) -> None:
    """R20 — reclaim bumps generation; prior owner writes fail closed."""
    run_id = "deliver-gen-fence"
    first = acquire_run_lease(repo, run_id)
    assert first["verdict"] == "pass"
    prior_gen = int(first["generation"])

    lock_path = run_lease_path_for(repo, run_id)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 888001
    meta["heartbeatAt"] = _stale_timestamp()
    meta["acquiredAt"] = meta["heartbeatAt"]
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    with patch("wave_lock.ship_lease_pid_alive", return_value=False):
        second = acquire_run_lease(repo, run_id)

    assert second["verdict"] == "pass"
    assert second.get("reclaimed") is True
    assert second["generation"] == prior_gen + 1

    # Prior owner's generation is refused on shared-state write.
    denied = assert_run_lease_write(repo, run_id, prior_gen)
    assert denied["verdict"] == "fail"
    assert denied["error"] == "run-lease-generation-stale"
    assert denied["halt"] == "run-lease-generation-stale"
    assert denied["expectedGeneration"] == prior_gen + 1

    allowed = assert_run_lease_write(repo, run_id, second["generation"])
    assert allowed["verdict"] == "pass"
