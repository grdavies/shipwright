"""PRD 325 phase 1 — merge detection + finalize under PR-number / slug drift."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_compound import (
    cmd_completion_finalize_if_merged,
    enrich_state_for_merge_check,
    merged_terminal_pr_by_head,
    target_merge_detected,
    terminal_pr_merged_via_host,
)
from wave_json_io import read_json, write_json
from wave_state import scoped_paths, slug_drift_payload


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def _write_state(tmp_path: Path, state: dict) -> Path:
    target = state["target"]["branch"]
    path = scoped_paths(tmp_path, target)["state"]
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, state)
    return path


def test_merged_terminal_pr_by_head_recovers_from_closed_filter(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    calls: list[str] = []

    def _host(_root, verb, **kwargs):
        calls.append(kwargs.get("state", verb))
        if verb == "pr-list" and kwargs.get("state") == "merged":
            return {"verdict": "ok", "data": []}
        if verb == "pr-list" and kwargs.get("state") == "closed":
            return {
                "verdict": "ok",
                "data": [{"number": 42, "state": "CLOSED", "url": "https://example/pr/42"}],
            }
        if verb == "pr-view":
            return {
                "verdict": "ok",
                "data": {
                    "number": 42,
                    "state": "MERGED",
                    "mergedAt": "2026-08-21T00:00:00Z",
                    "mergeCommit": {"oid": "abc123"},
                    "headRefName": "feat/recovered-target",
                },
            }
        return {"verdict": "ok", "data": []}

    with patch("wave_compound.host_verb", side_effect=_host):
        discovered, host_unavailable = merged_terminal_pr_by_head(tmp_path, "feat/recovered-target")

    assert not host_unavailable
    assert discovered is not None
    assert discovered["number"] == 42
    assert discovered["mergeCommit"] == "abc123"
    assert discovered["headRefName"] == "feat/recovered-target"
    assert "merged" in calls


def test_host_unavailable_returns_indeterminate_not_unmerged(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    state = {
        "target": {"branch": "feat/demo", "slug": "stale-slug"},
        "terminalPr": {},
    }

    with patch(
        "wave_compound.host_verb",
        return_value={"verdict": "fail", "error": "no auth"},
    ):
        info = terminal_pr_merged_via_host(tmp_path, state)

    assert info is not None
    assert info["status"] == "indeterminate"
    assert info["detail"] == "host-unavailable"
    assert info["merged"] is False

    with patch(
        "wave_compound.host_verb",
        return_value={"verdict": "fail", "error": "no auth"},
    ):
        merge_info = target_merge_detected(tmp_path, state)

    assert merge_info["status"] == "indeterminate"
    assert merge_info["detail"] == "host-unavailable"
    assert merge_info["merged"] is False


def test_slug_drift_reported_when_run_slug_differs(tmp_path: Path) -> None:
    drift = slug_drift_payload("old-run-slug", "feat/new-branch-slug", source="state")
    assert drift == {
        "runSlug": "old-run-slug",
        "branchSlug": "new-branch-slug",
        "source": "state",
    }

    _init_repo(tmp_path)
    state = {
        "target": {"branch": "feat/new-branch-slug", "slug": "old-run-slug"},
        "terminalPr": {"number": 7},
    }

    merge_info = {
        "merged": True,
        "status": "merged",
        "detail": "terminal-pr-host",
        "prNumber": 7,
        "mergeCommit": "deadbeef",
        "mergedAt": "2026-08-21T00:00:00Z",
    }
    with patch("wave_compound.terminal_pr_merged_via_host", return_value=merge_info):
        result = target_merge_detected(tmp_path, state)

    assert result["merged"] is True
    assert result["prNumber"] == 7
    assert result["slugDrift"]["runSlug"] == "old-run-slug"
    assert result["slugDrift"]["branchSlug"] == "new-branch-slug"


def test_enrich_state_recovers_stale_terminal_pr_number(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    state = {
        "target": {"branch": "feat/final-target", "slug": "final-target"},
        "terminalPr": {"number": 1},
    }

    def _host(_root, verb, **kwargs):
        if verb == "pr-view" and kwargs.get("number") == "1":
            return {"verdict": "ok", "data": {"state": "CLOSED", "number": 1}}
        if verb == "pr-list":
            return {
                "verdict": "ok",
                "data": [{"number": 99, "state": "MERGED"}],
            }
        if verb == "pr-view" and kwargs.get("number") == "99":
            return {
                "verdict": "ok",
                "data": {
                    "state": "MERGED",
                    "number": 99,
                    "mergeCommit": {"oid": "merged99"},
                    "headRefName": "feat/final-target",
                    "mergedAt": "2026-08-21T01:00:00Z",
                },
            }
        return {"verdict": "ok", "data": []}

    with patch("wave_compound.host_verb", side_effect=_host):
        enriched = enrich_state_for_merge_check(tmp_path, state)

    assert enriched["terminalPr"]["number"] == 99
    assert enriched["terminalPr"]["mergeCommit"] == "merged99"


def test_finalize_if_merged_idempotent_and_persists_recovery(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    state = {
        "target": {"branch": "feat/finalize-demo", "slug": "drifted-slug"},
        "completion": {"status": "completed-pending-merge", "at": "2026-08-21T00:00:00Z"},
        "terminalPr": {},
        "verdict": "running",
    }
    _write_state(tmp_path, state)
    merge_info = {
        "merged": True,
        "status": "merged",
        "detail": "terminal-pr-host-recovered",
        "prNumber": 55,
        "mergeCommit": "cafebabe",
        "mergedAt": "2026-08-21T02:00:00Z",
        "target": "feat/finalize-demo",
    }

    living_calls: list[int] = []

    def _living(_root, _state):
        living_calls.append(1)
        return {"verdict": "pass", "skipped": False}

    with (
        patch("wave_compound.target_merge_detected", return_value=merge_info),
        patch("wave_compound.invoke_living_docs_reconcile_finalize", side_effect=_living),
    ):
        with pytest.raises(SystemExit) as exc:
            cmd_completion_finalize_if_merged(tmp_path, [])
        assert exc.value.code == 0

    stored = read_json(scoped_paths(tmp_path, "feat/finalize-demo")["state"])
    assert stored["completion"]["status"] == "merged-complete"
    assert stored["completion"]["prNumber"] == 55
    assert stored["completion"]["mergeCommit"] == "cafebabe"
    assert stored["completion"]["slug"] == "finalize-demo"
    assert stored["verdict"] == "complete"
    assert living_calls == [1]

    with (
        patch("wave_compound.target_merge_detected", return_value=merge_info),
        patch("wave_compound.invoke_living_docs_reconcile_finalize", side_effect=_living) as living_mock,
    ):
        with pytest.raises(SystemExit) as exc:
            cmd_completion_finalize_if_merged(tmp_path, [])
        assert exc.value.code == 0

    living_mock.assert_not_called()


def test_unmerged_target_refuses_finalize(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    state = {
        "target": {"branch": "feat/not-merged", "slug": "not-merged"},
        "completion": {"status": "completed-pending-merge"},
        "verdict": "running",
    }
    _write_state(tmp_path, state)
    unmerged = {
        "merged": False,
        "status": "unmerged",
        "detail": "not-on-default",
        "target": "feat/not-merged",
    }
    with patch("wave_compound.target_merge_detected", return_value=unmerged):
        with pytest.raises(SystemExit) as exc:
            cmd_completion_finalize_if_merged(tmp_path, [])
        assert exc.value.code == 10
