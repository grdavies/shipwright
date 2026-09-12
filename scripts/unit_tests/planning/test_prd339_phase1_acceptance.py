"""PRD 339 phase-1 independent correctness acceptance (R35, R36, R38)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from prd339_phase1_acceptance import (
    PRD_339_R35_ACCEPTANCE_TEST,
    PRD_339_R36_ACCEPTANCE_TEST,
    PRD_339_R38_ACCEPTANCE_TEST,
    prd339_phase1_correctness_milestone,
)

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

PROJECT_KEY = "prd339-phase1-accept"
UNIT_ID = "tasks-339-phase1-accept"
ISSUE_NUMBER = "77"
HOST_UNIT_ID = "host-339-demo-bug"


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


def _seed_planning_issue(store: FixtureIssuesStore, *, number: int) -> None:
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
    record.number = number
    store._issues[record.id] = record
    store._persist()


def _seed_host_issue(store: FixtureIssuesStore, *, number: int) -> None:
    record = store.create(
        title="host bug",
        body=f"---\nid: {HOST_UNIT_ID}\ntype: gap\n---\n# Host bug\n",
        labels=["bug", f"sw:unit:{HOST_UNIT_ID}"],
        project_key="",
        artifact_type="gap",
        unit_id=HOST_UNIT_ID,
    )
    record.number = number
    store._issues[record.id] = record
    store._persist()


def test_phase1_gate_blocked_until_acceptance_modules_exist(tmp_path: Path) -> None:
    """R35/R36 — phase-1 gate blocks until amendment and secret-scan acceptance are green."""
    out = prd339_phase1_correctness_milestone(tmp_path)
    assert out["verdict"] == "blocked"
    assert out["cause"] == "prd-339-phase1-not-merged-green"
    blocked_tests = {item["test"] for item in out.get("blocked") or []}
    assert PRD_339_R35_ACCEPTANCE_TEST in blocked_tests
    assert PRD_339_R36_ACCEPTANCE_TEST in blocked_tests
    assert PRD_339_R38_ACCEPTANCE_TEST in blocked_tests


def test_phase1_gate_ready_on_repo(repo_root: Path) -> None:
    """R35/R36 — independently shippable correctness gate is green on merged phase work."""
    out = prd339_phase1_correctness_milestone(repo_root)
    if out.get("verdict") != "ready":
        blocked = out.get("blocked") or []
        detail = json.dumps(blocked, ensure_ascii=False, indent=2)
        raise AssertionError(f"phase1 gate not ready: {out.get('cause')} blocked={detail}")
    assert out.get("requirements") == ["R35", "R36", "R38"]


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
    planning_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/issue-store-fixture.json"
    )
    host_store = FixtureIssuesStore(
        repo / ".cursor/hooks/state/host-issue-fixture.json"
    )
    _seed_planning_issue(planning_store, number=int(ISSUE_NUMBER))
    _seed_host_issue(host_store, number=int(ISSUE_NUMBER))

    with pytest.raises(SystemExit) as exc:
        resolve_issue_entry(repo, ISSUE_NUMBER)
    assert exc.value.code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload.get("halt") == "issue-source-collision"
    assert set(payload.get("collisionSources") or []) == {
        ISSUE_SOURCE_PLANNING_STORE,
        ISSUE_SOURCE_HOST_REPO,
    }


def test_explicit_planning_store_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R38 — explicit planning-store selector resolves deterministically."""
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


def test_explicit_host_repo_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R38 — explicit host-repo selector resolves deterministically."""
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
        issue_source=ISSUE_SOURCE_HOST_REPO,
    )
    assert resolution["issueSource"] == ISSUE_SOURCE_HOST_REPO
    assert resolution["unitId"] == HOST_UNIT_ID
    assert resolution["issue"] == ISSUE_NUMBER
