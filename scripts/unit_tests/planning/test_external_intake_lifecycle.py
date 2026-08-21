"""Fixture harness for external issue triage lifecycle (PRD 280 tasks 1.4 / R22)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from issues_lib import FixtureIssuesStore, get_fixture_store
from planning_external_intake import (
    EXTERNAL_INTAKE_OUTCOMES,
    parse_external_intake_block,
)
from planning_gap_capture import capture_external_intake
from planning_store_facade import external_intake_txn, load_workflow_config


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    (tmp_path / ".cursor" / "hooks" / "state").mkdir(parents=True, exist_ok=True)


def _issue_store_cfg(project_key: str = "external-intake-fixture") -> dict:
    return {
        "version": 1,
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
                "hierarchy": {"epicSubIssues": True},
            }
        },
        "host": {"provider": "github"},
    }


@pytest.fixture
def intake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    _init_repo(root)
    cfg = _issue_store_cfg()
    (root / ".cursor" / "workflow.config.json").write_text(json.dumps(cfg), encoding="utf-8")
    get_fixture_store(root).clear()
    return root


def test_external_intake_happy_path_brief(intake_repo: Path) -> None:
    cfg = load_workflow_config(intake_repo)
    receive = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-receive",
        signal_id="sig-happy",
        title="External report",
        signal_class="prod",
    )
    assert receive["verdict"] == "ok"
    issue_id = receive["issueId"]

    pipeline_steps = [
        "external-intake-classify",
        "external-intake-verify",
        "external-intake-actionability",
    ]
    for verb in pipeline_steps:
        step = external_intake_txn(intake_repo, cfg, verb=verb, issue_id=issue_id)
        assert step["verdict"] == "ok", step

    promote = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-promote",
        issue_id=issue_id,
        gap_unit_id="gap-external-happy",
        comment="Promoted to brief",
    )
    assert promote["verdict"] == "ok"
    assert promote["outcome"] == "brief"
    assert "sw:gap" in (promote.get("gapLabels") or [])

    store: FixtureIssuesStore = get_fixture_store(intake_repo)
    record = store.get(str(issue_id))
    block = parse_external_intake_block(record.body)
    assert block["state"] == "ready-brief"
    assert "sw:source:external" in record.labels


def test_external_intake_reporter_blocked(intake_repo: Path) -> None:
    cfg = load_workflow_config(intake_repo)
    receive = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-receive",
        signal_id="sig-blocked",
        title="Need more info",
    )
    issue_id = receive["issueId"]
    for verb in ("external-intake-classify", "external-intake-verify"):
        external_intake_txn(intake_repo, cfg, verb=verb, issue_id=issue_id)

    blocked = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-ask-reporter",
        issue_id=issue_id,
        comment="Please attach logs",
    )
    assert blocked["verdict"] == "ok"
    assert blocked["outcome"] == "question"

    store = get_fixture_store(intake_repo)
    record = store.get(str(issue_id))
    assert parse_external_intake_block(record.body)["state"] == "blocked-reporter"
    assert any("Please attach logs" in c.body for c in record.comments)


def test_external_intake_closure_path(intake_repo: Path) -> None:
    cfg = load_workflow_config(intake_repo)
    receive = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-receive",
        signal_id="sig-close",
        title="Duplicate report",
    )
    issue_id = receive["issueId"]
    external_intake_txn(intake_repo, cfg, verb="external-intake-classify", issue_id=issue_id)
    external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-duplicate-check",
        issue_id=issue_id,
    )
    closed = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-close",
        issue_id=issue_id,
        comment="Duplicate of planning#123",
    )
    assert closed["verdict"] == "ok"
    assert closed["outcome"] == "closure"
    record = get_fixture_store(intake_repo).get(str(issue_id))
    assert parse_external_intake_block(record.body)["state"] == "closed"


def test_illegal_transition_fail_closed(intake_repo: Path) -> None:
    cfg = load_workflow_config(intake_repo)
    receive = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-receive",
        signal_id="sig-illegal",
        title="Skip states",
    )
    issue_id = receive["issueId"]
    skipped = external_intake_txn(
        intake_repo,
        cfg,
        verb="external-intake-promote",
        issue_id=issue_id,
        gap_unit_id="gap-should-fail",
    )
    assert skipped["verdict"] == "fail"
    assert "illegal-transition" in str(skipped.get("error"))


def test_feedback_capture_uses_store_verbs_only(intake_repo: Path) -> None:
    out = capture_external_intake(
        intake_repo,
        signal_id="feedback-route",
        title="Production regression",
        payload="token=REDACT_ME secret stuff",
        outcome="question",
        comment="What release introduced this?",
        dry_run=False,
    )
    assert out["verdict"] == "pass"
    assert out["orchestratorBoundary"] == "store-verbs-only"
    assert out["outcome"] == "question"
    record = get_fixture_store(intake_repo).get(str(out["issueId"]))
    comment_bodies = " ".join(c.body for c in record.comments)
    assert "REDACT_ME" not in comment_bodies


def test_outcomes_are_exactly_three() -> None:
    assert EXTERNAL_INTAKE_OUTCOMES == frozenset({"brief", "question", "closure"})
