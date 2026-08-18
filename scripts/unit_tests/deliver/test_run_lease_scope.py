"""PRD 276 R21 — run lease scope is local to git common-dir; uncertain ownership fail-closed."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_lock import (
    acquire_run_lease,
    assert_run_lease_write,
    reclaim_stale_run_lease,
    run_lease_locks_dir,
    run_lease_path_for,
    RUN_LEASE_LOCKS_DIR_NAME,
)


@pytest.fixture
def twin_repos(tmp_path: Path) -> tuple[Path, Path]:
    a = tmp_path / "clone-a"
    b = tmp_path / "clone-b"
    a.mkdir()
    b.mkdir()
    (a / ".cursor").mkdir()
    (b / ".cursor").mkdir()
    return a, b


def test_lease_scope_local_common_dir_uncertain_fail_closed(
    twin_repos: tuple[Path, Path],
) -> None:
    """R21 — lease scope local to git common-dir; uncertain ownership fail-closed."""
    clone_a, clone_b = twin_repos
    run_id = "deliver-scope-local"

    with patch("wave_lock._canonical_repo_root_for_locks", return_value=clone_a):
        first = acquire_run_lease(clone_a, run_id)
        assert first["verdict"] == "pass"
        path_a = run_lease_path_for(clone_a, run_id)
        assert path_a.is_file()
        assert RUN_LEASE_LOCKS_DIR_NAME in path_a.parts
        assert path_a.is_relative_to(run_lease_locks_dir(clone_a))

    # Distinct common-dir → independent lock namespace (no cross-clone coupling).
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=clone_b):
        other = acquire_run_lease(clone_b, run_id)
        assert other["verdict"] == "pass"
        path_b = run_lease_path_for(clone_b, run_id)
        assert path_b.is_file()
        assert path_a.resolve() != path_b.resolve()

    # Uncertain ownership (missing host/pid) → reclaim and acquire fail closed.
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=clone_a):
        lock_path = run_lease_path_for(clone_a, run_id)
        meta = json.loads(lock_path.read_text(encoding="utf-8"))
        meta.pop("host", None)
        meta.pop("pid", None)
        lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

        reclaimed, _gen = reclaim_stale_run_lease(
            lock_path,
            root=clone_a,
            reclaiming_run_id=run_id,
            takeover_reason="stale-heartbeat-dead-pid",
        )
        assert reclaimed is False

        blocked = acquire_run_lease(clone_a, run_id)
        assert blocked["verdict"] == "fail"
        assert blocked["error"] == "run-lease-ownership-uncertain"
        assert blocked["halt"] == "run-lease-ownership-uncertain"
        assert "resumeCommand" in blocked

        # Cross-host without ack also fails closed (no automatic cross-clone reclaim).
        meta = {
            "kind": "deliver-run-lease",
            "runId": run_id,
            "generation": 1,
            "owner": "other-host:1",
            "host": "other-host",
            "pid": 1,
            "acquiredAt": "2000-01-01T00:00:00Z",
            "heartbeatAt": "2000-01-01T00:00:00Z",
        }
        lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
        cross = acquire_run_lease(clone_a, run_id)
        assert cross["verdict"] == "fail"
        assert cross["error"] in ("run-lease-cross-host", "run-lease-held")
        assert cross.get("halt")

        fenced = assert_run_lease_write(clone_a, run_id, 1)
        assert fenced["verdict"] == "fail"
