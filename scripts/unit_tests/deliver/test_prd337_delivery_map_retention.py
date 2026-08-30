"""PRD 337 R14 — terminal PR delivery maps survive orchestrator teardown."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import deliver_closeout as dc

HEAD = "a" * 40
PR_NUMBER = 337
MAPPING_PAYLOAD = {
    "prNumber": str(PR_NUMBER),
    "prdUnitId": "prd-337-workflow-runtime-autonomy-lifecycle",
    "deliverySlug": "workflow-runtime-autonomy-lifecycle",
    "targetBranch": "feat/workflow-runtime-autonomy-lifecycle",
    "headSha": HEAD,
    "runSlug": "workflow-runtime-autonomy-lifecycle",
    "prUrl": "https://github.com/acme/shipwright/pull/337",
}


def _provision_orchestrator_worktree(repo: Path) -> Path:
    branch = "feat/workflow-runtime-autonomy-lifecycle"
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-q", "-m", "integration branch"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    orch_dir = repo.parent / "orch-worktree"
    subprocess.run(["git", "checkout", "-q", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "worktree", "add", "-q", str(orch_dir), branch],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return orch_dir


def _teardown_orchestrator_state(repo: Path, orch_dir: Path) -> None:
    deliver_state = orch_dir / ".cursor" / "sw-deliver-state.json"
    if deliver_state.is_file():
        deliver_state.unlink()
    orch_closeout = orch_dir / ".sw" / "deliver-closeout"
    if orch_closeout.is_dir():
        shutil.rmtree(orch_closeout)
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(orch_dir)],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def test_terminal_pr_mapping_persists_under_primary_closeout(tmp_git_repo: Path) -> None:
    """B — record from orchestrator cwd lands on primary .sw/deliver-closeout."""
    orch_dir = _provision_orchestrator_worktree(tmp_git_repo)
    try:
        result = dc.record_pr_delivery_mapping(orch_dir, MAPPING_PAYLOAD)
        assert result["verdict"] == "pass"
        storage = tmp_git_repo / ".sw" / "deliver-closeout"
        map_path = storage / "pr-delivery-map" / f"pr-{PR_NUMBER}.json"
        assert map_path.is_file()
        assert not (orch_dir / ".sw" / "deliver-closeout").exists()
        assert result["storageRoot"] == str(tmp_git_repo.resolve())
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(orch_dir)],
            cwd=tmp_git_repo,
            check=True,
            capture_output=True,
        )


def test_delivery_map_survives_orchestrator_teardown(tmp_git_repo: Path) -> None:
    """I — delete transient orchestrator state; lookup still resolves delivery."""
    orch_dir = _provision_orchestrator_worktree(tmp_git_repo)
    recorded = dc.record_pr_delivery_mapping(orch_dir, MAPPING_PAYLOAD)
    assert recorded["verdict"] == "pass"
    _teardown_orchestrator_state(tmp_git_repo, orch_dir)

    resolved = dc.resolve_delivery_for_pr(tmp_git_repo, PR_NUMBER)
    assert resolved["verdict"] == "pass"
    assert resolved["prdUnitId"] == MAPPING_PAYLOAD["prdUnitId"]
    assert resolved["deliverySlug"] == MAPPING_PAYLOAD["deliverySlug"]
    assert Path(resolved["mappingPath"]).is_file()


def test_closeout_index_survives_orchestrator_teardown(tmp_git_repo: Path) -> None:
    """E — index.json remains on primary root after orchestrator removal."""
    orch_dir = _provision_orchestrator_worktree(tmp_git_repo)
    dc.record_pr_delivery_mapping(orch_dir, MAPPING_PAYLOAD)
    _teardown_orchestrator_state(tmp_git_repo, orch_dir)

    index_path = dc.index_path(tmp_git_repo)
    assert index_path.is_file()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["byPr"][str(PR_NUMBER)].endswith(f"pr-delivery-map/pr-{PR_NUMBER}.json")


def test_mapping_write_is_atomic(tmp_git_repo: Path) -> None:
    """A — no stray .tmp files after successful record."""
    result = dc.record_pr_delivery_mapping(tmp_git_repo, MAPPING_PAYLOAD)
    assert result["verdict"] == "pass"
    map_dir = tmp_git_repo / ".sw" / "deliver-closeout" / "pr-delivery-map"
    assert list(map_dir.glob("*.tmp")) == []
