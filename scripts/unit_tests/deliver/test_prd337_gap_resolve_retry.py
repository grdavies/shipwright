"""PRD 337 R11 — bounded gap-closeout issue-search retry/backoff + exhaustion halt."""

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

import wave_living_docs as wld  # noqa: E402
from halt_resume import validate_halt_resume  # noqa: E402
from issues_lib import FixtureIssuesStore, IssueRateLimited  # noqa: E402
from planning_canonical import compose_issue_body, type_label  # noqa: E402


@pytest.fixture(autouse=True)
def shipwright_scripts_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHIPWRIGHT_SCRIPTS", str(SCRIPT_DIR.resolve()))
    monkeypatch.delenv("SW_DELIVER_RUN_ID", raising=False)
    monkeypatch.delenv("SW_RUN_ID", raising=False)


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text(".cursor/\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "init")
    _git(tmp_path, "branch", "-M", "main")
    _git(tmp_path, "checkout", "-qb", "feat/closeout-gap")
    (tmp_path / ".cursor").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _issue_store_cfg(project_key: str = "gap-closeout-337") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "location": "separate-project",
            }
        },
        "host": {"provider": "github"},
    }


def _seed_gap_scheduled_for_prd(
    root: Path,
    store: FixtureIssuesStore,
    project_key: str,
    prd: str,
    gap_unit: str,
) -> None:
    schedule_label = f"sw:gap-schedule:PRD-{prd.zfill(3)}"
    body = compose_issue_body(
        project_key,
        "gap",
        gap_unit,
        f"---\nid: {gap_unit}\ntype: gap\nstatus: scheduled\n---\n# gap\n",
    )
    rec = store.create(
        title="gap",
        body=body,
        labels=[
            type_label("gap"),
            "sw:gap-scheduled",
            schedule_label,
            f"sw:unit:{gap_unit}",
        ],
        project_key=project_key,
        artifact_type="gap",
        unit_id=gap_unit,
    )
    (root / ".cursor/hooks/state/issue-store-unit-index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "units": {f"{project_key}:{gap_unit}": rec.id},
            }
        ),
        encoding="utf-8",
    )


def _deliver_state(prd: str = "337") -> dict:
    return {
        "runId": "deliver-test-gap-closeout",
        "prd_number": prd,
        "source_task_list": (
            "docs/prds/337-workflow-runtime-autonomy-lifecycle/"
            "tasks-337-workflow-runtime-autonomy-lifecycle.md"
        ),
        "target": {"branch": "feat/workflow-runtime-autonomy-lifecycle", "slug": "workflow-runtime"},
        "phases": {"4": {"slug": "bound-living-doc-gap-closeout-small", "status": "green-merged"}},
        "completion": {"status": "completed-pending-merge"},
    }


def test_gap_closeout_immediate_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """O — gap resolve succeeds on first issue-search attempt."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = _init_repo(tmp_path)
    project_key = "gap-closeout-337"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    _seed_gap_scheduled_for_prd(root, store, project_key, "337", "gap-337-closeout")

    out = wld.facade_gap_resolve_with_retry(
        root,
        "337",
        worktree=root,
        state=_deliver_state(),
        sleep_fn=lambda _s: None,
    )
    assert out.get("verdict") == "pass"
    retry = out.get("gapCloseoutRetry") or {}
    assert retry.get("attempts") == 1
    assert retry.get("exhausted") is False


def test_gap_closeout_bounded_recovery(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E/S — rate-limited issue search recovers within retry budget."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = _init_repo(tmp_path)
    project_key = "gap-closeout-337"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    _seed_gap_scheduled_for_prd(root, store, project_key, "337", "gap-337-closeout")

    calls = {"n": 0}

    def _flaky_resolve(worktree: Path, prd: str, *, pr: str = "") -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            return {
                "verdict": "resolution-partial",
                "error": "rate-limited",
                "retryable": True,
                "reason": "rate-limited",
            }
        return {"verdict": "pass", "flipped": ["gap-337-closeout"], "error": None}

    with patch.object(wld, "facade_gap_resolve", side_effect=_flaky_resolve):
        out = wld.facade_gap_resolve_with_retry(
            root,
            "337",
            worktree=root,
            state=_deliver_state(),
            sleep_fn=lambda _s: None,
        )

    assert out.get("verdict") == "pass"
    assert calls["n"] == 2
    retry = out.get("gapCloseoutRetry") or {}
    assert retry.get("attempts") == 2
    assert retry.get("exhausted") is False


def test_gap_closeout_retry_exhaustion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B — exhausted retry budget returns typed halt + resumeCommand."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = _init_repo(tmp_path)
    project_key = "gap-closeout-337"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    state_path = root / ".cursor" / "sw-deliver-state.json"
    state_path.write_text(json.dumps(_deliver_state()), encoding="utf-8")
    (root / ".cursor" / "sw-deliver-plan.json").write_text("{}", encoding="utf-8")

    def _always_rate_limited(worktree: Path, prd: str, *, pr: str = "") -> dict[str, object]:
        return {
            "verdict": "resolution-partial",
            "error": "rate-limited",
            "retryable": True,
            "reason": "cumulative-wait-exhausted",
        }

    captured: dict = {}

    def _capture_fail(error: str, exit_code: int = 2, **extra) -> None:
        captured["payload"] = {"verdict": "fail", "error": error, **extra}
        raise SystemExit(exit_code)

    with (
        patch.object(wld, "facade_gap_resolve", side_effect=_always_rate_limited),
        patch.object(
            wld,
            "gap_closeout_retry_config",
            return_value={"maxAttempts": 2, "baseBackoffSeconds": 0.0, "capBackoffSeconds": 0.0},
        ),
        patch.object(wld, "facade_set_index_status", return_value={"verdict": "skipped"}),
        patch.object(wld, "target_merge_detected", return_value=False),
        patch.object(wld, "fail", side_effect=_capture_fail),
        pytest.raises(SystemExit) as excinfo,
    ):
        wld.cmd_reconcile(root, [])

    assert excinfo.value.code == 30
    payload = captured["payload"]
    assert payload.get("verdict") == "fail"
    assert payload.get("halt") == "gap-closeout-retry-exhausted"
    assert payload.get("mergedCompleteRefused") is True
    assert "resumeCommand" in payload
    halt = payload.get("haltResume") or {}
    ok, errors = validate_halt_resume(halt)
    assert ok, errors
    assert halt.get("haltCause") == "gap-closeout-retry-exhausted"


def test_gap_closeout_issue_rate_limited_exception_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """IssueRateLimited from issue search is retried then succeeds."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = _init_repo(tmp_path)
    project_key = "gap-closeout-337"
    cfg = _issue_store_cfg(project_key)
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    store = FixtureIssuesStore(root / ".cursor/hooks/state/issue-store-fixture.json")
    _seed_gap_scheduled_for_prd(root, store, project_key, "337", "gap-337-closeout")

    calls = {"n": 0}

    def _flaky(worktree: Path, prd: str, *, pr: str = "") -> dict[str, object]:
        calls["n"] += 1
        if calls["n"] == 1:
            raise IssueRateLimited("simulated", cumulative_wait_ms=5, reason="rate-limited")
        return {"verdict": "pass", "flipped": ["gap-337-closeout"], "error": None}

    with patch.object(wld, "facade_gap_resolve", side_effect=_flaky):
        out = wld.facade_gap_resolve_with_retry(
            root,
            "337",
            worktree=root,
            state=_deliver_state(),
            sleep_fn=lambda _s: None,
        )

    assert out.get("verdict") == "pass"
    assert calls["n"] == 2
