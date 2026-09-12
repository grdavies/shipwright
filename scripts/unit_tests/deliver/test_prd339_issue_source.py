"""PRD 339 R38 — disambiguate planning-store vs host-repo deliver issue entry."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from issues_lib import FixtureIssuesStore  # noqa: E402
from planning_canonical import compose_issue_body, type_label  # noqa: E402
from planning_unit_status import (  # noqa: E402
    ISSUE_SOURCE_HOST_REPO,
    ISSUE_SOURCE_PLANNING_STORE,
    resolve_issue_entry,
)
from wave_deliver import cmd_run  # noqa: E402

PROJECT_KEY = "prd339-issue-source"
UNIT_ID = "tasks-339-demo-feature"
ISSUE_NUMBER = "42"


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
    (tmp_path / ".gitignore").write_text(".cursor/\n.sw-worktrees/\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-qm", "init")
    _git(tmp_path, "branch", "-M", "main")
    return tmp_path


def _separate_project_cfg() -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": PROJECT_KEY,
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "planning-org",
                    "repo": "planning-store",
                },
            }
        },
        "host": {"provider": "github"},
    }


def _write_task_list(repo: Path) -> str:
    rel = "docs/prds/339-demo-feature/tasks-339-demo-feature.md"
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\ntype: tasks\nid: tasks-339-demo-feature\nfrozen: true\n---\n\n"
        "# Tasks\n\n### 1. Demo\n\n- [ ] 1.1 Work\n",
        encoding="utf-8",
    )
    _git(repo, "add", rel)
    _git(repo, "commit", "-qm", "add tasks")
    return rel


def _seed_planning_issue(store: FixtureIssuesStore, *, number: int | None = None) -> None:
    body = compose_issue_body(
        PROJECT_KEY,
        "tasks",
        UNIT_ID,
        f"---\nid: {UNIT_ID}\ntype: tasks\nfrozen: true\n---\n# Tasks\n",
    )
    record = store.create(
        title="tasks",
        body=body,
        labels=[type_label("tasks"), f"sw:unit:{UNIT_ID}"],
        project_key=PROJECT_KEY,
        artifact_type="tasks",
        unit_id=UNIT_ID,
    )
    if number is not None:
        record.number = number
        store._issues[record.id] = record
        store._persist()


def _seed_host_issue(store: FixtureIssuesStore, *, number: int) -> None:
    record = store.create(
        title="unrelated host bug",
        body="No planning markers here.",
        labels=["bug"],
        project_key="",
        artifact_type="",
        unit_id="",
    )
    record.number = number
    store._issues[record.id] = record
    store._persist()


def _capture_fail(capsys: pytest.CaptureFixture[str], fn) -> dict:
    with pytest.raises(SystemExit) as exc:
        fn()
    assert exc.value.code == 2
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload.get("verdict") == "fail"
    return payload


def test_same_number_issue_collision(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R38 — same-number host/planning issues fail closed without selector."""
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.setenv("SW_HOST_ISSUES_FIXTURE", "1")
    repo = _init_repo(tmp_path)
    (repo / ".cursor").mkdir(parents=True, exist_ok=True)
    (repo / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_separate_project_cfg()),
        encoding="utf-8",
    )
    _write_task_list(repo)
    planning_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/issue-store-fixture.json"
    )
    host_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/host-issue-fixture.json"
    )
    _seed_planning_issue(planning_store, number=int(ISSUE_NUMBER))
    _seed_host_issue(host_store, number=int(ISSUE_NUMBER))

    payload = _capture_fail(
        capsys,
        lambda: resolve_issue_entry(repo, ISSUE_NUMBER),
    )
    assert payload.get("halt") == "issue-source-collision"
    assert set(payload.get("collisionSources") or []) == {
        ISSUE_SOURCE_PLANNING_STORE,
        ISSUE_SOURCE_HOST_REPO,
    }


def test_explicit_planning_store_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    monkeypatch.setenv("SW_HOST_ISSUES_FIXTURE", "1")
    repo = _init_repo(tmp_path)
    (repo / ".cursor").mkdir(parents=True, exist_ok=True)
    (repo / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_separate_project_cfg()),
        encoding="utf-8",
    )
    planning_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/issue-store-fixture.json"
    )
    host_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/host-issue-fixture.json"
    )
    _seed_planning_issue(planning_store, number=int(ISSUE_NUMBER))
    _seed_host_issue(host_store, number=int(ISSUE_NUMBER))

    resolution = resolve_issue_entry(
        repo,
        ISSUE_NUMBER,
        issue_source=ISSUE_SOURCE_PLANNING_STORE,
    )
    assert resolution["issueSource"] == ISSUE_SOURCE_PLANNING_STORE
    assert resolution["unitId"] == UNIT_ID
    assert resolution["issue"] == ISSUE_NUMBER


def test_run_entry_prints_origin_and_unit_id(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    repo = _init_repo(tmp_path)
    (repo / ".cursor").mkdir(parents=True, exist_ok=True)
    (repo / ".cursor" / "workflow.config.json").write_text(
        json.dumps(_separate_project_cfg()),
        encoding="utf-8",
    )
    rel = _write_task_list(repo)
    planning_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/issue-store-fixture.json"
    )
    _seed_planning_issue(planning_store, number=int(ISSUE_NUMBER))
    _git(repo, "checkout", "-qb", "feat/demo-feature")
    _git(repo, "commit", "--allow-empty", "-qm", "feature")
    _git(repo, "checkout", "-q", "main")

    with pytest.raises(SystemExit) as exc:
        cmd_run(repo, ["run", "--issue", ISSUE_NUMBER])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    assert (
        f"issue-source={ISSUE_SOURCE_PLANNING_STORE} sw-unit-id={UNIT_ID}"
        in captured.err
    )
    payload = json.loads(captured.out)
    assert payload["issueResolution"]["issueSource"] == ISSUE_SOURCE_PLANNING_STORE
    assert payload["issueResolution"]["swUnitId"] == UNIT_ID
