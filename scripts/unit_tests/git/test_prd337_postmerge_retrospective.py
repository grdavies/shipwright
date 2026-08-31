"""PRD 337 R16 — post-merge retrospective dispatch idempotency and resume."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc
import wave_terminal as wt

RUN_ID = "deliver-0282a9d6a7bd4e48a2dd4f396a34cb80"
MERGE_COMMIT = "c" * 40
MERGE_INFO = {
    "merged": True,
    "mergeCommit": MERGE_COMMIT,
    "prNumber": 337,
    "mergedAt": "2026-08-30T12:00:00Z",
}


def test_postmerge_retrospective_Z_missing_merge_proof(tmp_git_repo: Path) -> None:
    """Z — missing merge proof refuses dispatch."""
    result = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info={"merged": False},
    )
    assert result["verdict"] == "fail"
    assert result["error"] == "merge-not-confirmed"
    assert "finalize run" in result["resumeCommand"]


def test_postmerge_retrospective_O_first_dispatch(tmp_git_repo: Path) -> None:
    """O — first dispatch persists state and invokes post-merge retrospective once."""
    result = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    assert result["verdict"] == "pass"
    assert result["invoke"] == dc.POST_MERGE_RETRO_INVOKE
    assert result["awaitAgent"] is True
    assert result["dispatch"]["dispatchCount"] == 1
    path = dc.post_merge_retrospective_dispatch_path(tmp_git_repo, RUN_ID)
    assert path.is_file()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["status"] == "dispatched"
    assert persisted["invoke"] == "/sw-retrospective --post-merge"


def test_postmerge_retrospective_M_repeated_finalize_no_duplicate(tmp_git_repo: Path) -> None:
    """M — repeated finalize does not duplicate retrospective dispatch."""
    first = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    second = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    assert first["dispatch"]["dispatchedAt"] == second["dispatch"]["dispatchedAt"]
    assert second["idempotent"] is True
    assert second["resume"] is True
    assert second["dispatch"]["dispatchCount"] == 1


def test_postmerge_retrospective_B_merge_transition_mismatch(tmp_git_repo: Path) -> None:
    """B — merge commit transition mismatch fails closed."""
    dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    other = dict(MERGE_INFO)
    other["mergeCommit"] = "d" * 40
    blocked = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=other,
    )
    assert blocked["verdict"] == "fail"
    assert blocked["error"] == "merge-commit-mismatch"


def test_postmerge_retrospective_I_retrospective_command(tmp_git_repo: Path) -> None:
    """I — invoke contract is exactly /sw-retrospective --post-merge."""
    result = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    assert result["invoke"] == "/sw-retrospective --post-merge"


def test_postmerge_retrospective_E_interrupted_dispatch_resumes(tmp_git_repo: Path) -> None:
    """E — interrupted dispatch resumes from durable state without rewrite."""
    first = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    path = dc.post_merge_retrospective_dispatch_path(tmp_git_repo, RUN_ID)
    before = path.read_text(encoding="utf-8")
    resumed = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    after = path.read_text(encoding="utf-8")
    assert before == after
    assert resumed["resume"] is True
    assert resumed["invoke"] == first["invoke"]
    assert resumed["dispatch"]["resumeCommand"] == first["dispatch"]["resumeCommand"]


def test_postmerge_retrospective_S_idempotent_after_complete(tmp_git_repo: Path) -> None:
    """S — completed dispatch is a noop on subsequent finalize."""
    dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    dc.mark_post_merge_retrospective_complete(tmp_git_repo, RUN_ID, merge_commit=MERGE_COMMIT)
    again = dc.dispatch_post_merge_retrospective(
        tmp_git_repo,
        run_id=RUN_ID,
        merge_info=MERGE_INFO,
    )
    assert again["noop"] is True
    assert again["idempotent"] is True
    assert again.get("awaitAgent") is not True


def test_finalize_run_wires_post_merge_retrospective(tmp_git_repo: Path) -> None:
    """finalize_run attaches post-merge retrospective dispatch after immutable write."""
    state = {
        "runId": RUN_ID,
        "immutable": True,
        "terminalMerge": {
            "mergeCommit": MERGE_COMMIT,
            "prNumber": 337,
            "mergedAt": "2026-08-30T12:00:00Z",
        },
    }
    with (
        patch("wave_run_adopt.assess_proven_run_scoped_identity", return_value={"proven": True}),
        patch("wave_transition_receipt.read_terminal_receipt", return_value={"mergeCommit": MERGE_COMMIT}),
        patch("wave_deliver_loop.load_finalize_checkpoint", return_value={"status": "complete"}),
        patch("wave_deliver_loop.finalize_checkpoint_needs_repair", return_value=False),
    ):
        payload = wt.finalize_run(tmp_git_repo, RUN_ID, state)
    retro = payload["postMergeRetrospective"]
    assert retro["verdict"] == "pass"
    assert payload.get("invoke") == dc.POST_MERGE_RETRO_INVOKE
    assert payload.get("awaitAgent") is True
