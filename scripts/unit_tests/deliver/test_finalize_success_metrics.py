"""PRD 276 R1/R18 — mirror evidence + measurable finalize success metrics."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import ensure_terminal_ship_run_state, load_finalize_checkpoint
from wave_json_io import write_json
from wave_run_paths import run_directory, state_path
from wave_state import (
    ensure_run_scoped_state_mirrored,
    load_run_scoped_state,
    scoped_paths,
    write_run_local_lease,
)
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run
from wave_transition_receipt import read_terminal_receipt


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def test_terminal_ship_mirrors_missing_run_state(tmp_path: Path) -> None:
    """R1 — slug state mirrored into run-scoped path before terminal-ship."""
    _init_repo(tmp_path)
    run_id = "deliver-mirror-r1"
    slug_state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/mirror-demo", "slug": "mirror-demo"},
        "terminalPr": {"number": 11},
        "phases": {"1": {"status": "green-merged", "slug": "a"}},
        "compoundShip": {"premergeDone": True},
    }
    # Only slug-scoped state exists (the fragile gap from #698).
    slug_path = scoped_paths(tmp_path, "feat/mirror-demo")["state"]
    slug_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(slug_path, slug_state)
    assert not state_path(tmp_path, run_id).is_file()

    mirrored = ensure_run_scoped_state_mirrored(tmp_path, dict(slug_state))
    assert mirrored.get("runId") == run_id
    assert state_path(tmp_path, run_id).is_file()
    loaded = load_run_scoped_state(tmp_path, run_id)
    assert loaded.get("target", {}).get("branch") == "feat/mirror-demo"

    # Driver helper used at terminal-ship boundary is idempotent.
    again = ensure_terminal_ship_run_state(tmp_path, dict(slug_state))
    assert again.get("runId") == run_id
    assert load_run_scoped_state(tmp_path, run_id).get("verdict") == "running"


def test_finalize_retry_completion_and_no_duplicate_transitions(tmp_path: Path) -> None:
    """R18 — measurable retry completion; receipt/immutable not duplicated."""
    _init_repo(tmp_path)
    run_id = "deliver-metrics-r18"
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/metrics-demo", "slug": "metrics-demo"},
        "terminalPr": {"number": 55, "headBranch": "feat/metrics-demo"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {},
        "phaseWorktrees": {},
    }
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/metrics-demo")
    acquire_target_lock(tmp_path, "feat/metrics-demo", run_id)

    merge_info = {
        "merged": True,
        "mergeCommit": "metricscafe01",
        "prNumber": 55,
        "mergedAt": "2026-08-17T15:00:00Z",
        "detail": "terminal-pr-host",
    }

    # Fault then recover — restart recovery bound.
    t0 = time.monotonic()
    with (
        patch("wave_compound.terminal_pr_merged_via_host", return_value=merge_info),
        patch(
            "wave_terminal.close_run_projections",
            side_effect=RuntimeError("transient"),
        ),
    ):
        partial = finalize_run(tmp_path, run_id, state, actor="tester")
    assert partial["verdict"] == "fail"

    with patch("wave_compound.terminal_pr_merged_via_host", return_value=merge_info):
        done = finalize_run(tmp_path, run_id, load_run_scoped_state(tmp_path, run_id), actor="tester")
    elapsed = time.monotonic() - t0

    assert done["verdict"] == "pass"
    assert done["immutable"] is True
    assert elapsed < 30.0  # measurable restart recovery bound (R18)

    receipt = read_terminal_receipt(tmp_path, run_id)
    assert receipt is not None
    assert receipt["mergeCommit"] == "metricscafe01"
    receipt_path = run_directory(tmp_path, run_id) / "terminal-receipt.json"
    body_before = receipt_path.read_text(encoding="utf-8")

    # Second success path must not rewrite a completed receipt (no duplicate transition).
    with patch("wave_compound.terminal_pr_merged_via_host", return_value=merge_info):
        again = finalize_run(tmp_path, run_id, load_run_scoped_state(tmp_path, run_id))
    assert again["verdict"] == "pass"
    assert again.get("note") == "already finalized"
    assert receipt_path.read_text(encoding="utf-8") == body_before

    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt["status"] == "complete"
    assert ckpt["lastCompletedPhase"] == "immutable"
