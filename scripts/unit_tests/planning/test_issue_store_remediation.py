"""Unit tests for issue-store cutover remediation (pagination, types, labels)."""

from __future__ import annotations

from pathlib import Path

import pytest

from planning_canonical import (
    GAP_LABEL_RESOLVED,
    gap_status_from_labels,
    gap_status_label,
    infer_artifact_type,
    status_from_labels,
    status_label,
)
from planning_migrate_issue_store import (
    WALK_ROOTS,
    _consumer_status_for_artifact,
    _frontmatter_status_for_lifecycle,
    _legacy_index_status_map,
    extract_lifecycle_from_file,
    infer_unit_id,
    lifecycle_equal,
    render_file_with_lifecycle,
)
from planning_migrate_issue_store import ArtifactLifecycle


def test_walk_roots_include_brainstorms_and_decisions() -> None:
    assert "docs/brainstorms" in WALK_ROOTS
    assert "docs/decisions" in WALK_ROOTS


def test_infer_artifact_type_planning_unit_paths() -> None:
    assert infer_artifact_type("docs/planning/brainstorm/brainstorm-x/brainstorm-x.md") == "brainstorm"
    assert infer_artifact_type("docs/planning/decision/decision-x/decision-x.md") == "decision"
    assert infer_artifact_type("docs/prds/005/foo/amendments/A1-bar.md") == "amendment"


def test_infer_unit_id_brainstorm_slug() -> None:
    rel = "docs/brainstorms/2026-06-24-native-local-review-panel-requirements.md"
    uid = infer_unit_id(rel, "---\ntopic: x\n---\n# body")
    assert uid.startswith("brainstorm-")
    assert "native-local-review" in uid


def test_gap_status_labels_normalized() -> None:
    assert gap_status_label("resolved") == GAP_LABEL_RESOLVED
    assert gap_status_from_labels(["sw:gap-resolved"]) == "resolved"
    assert gap_status_from_labels(["resolved"]) == "resolved"


def test_status_labels_round_trip() -> None:
    label = status_label("complete")
    assert status_from_labels([label]) == "complete"


def test_legacy_index_status_map_reads_complete_rows(repo_root: Path) -> None:
    mapping = _legacy_index_status_map(repo_root)
    assert mapping.get("005") == "complete"
    assert _consumer_status_for_artifact(repo_root, "005-prd-native-local-review-panel", "prd") == "complete"


def test_completion_log_marks_044_complete(repo_root: Path) -> None:
    import planning_migrate_issue_store as m

    m._COMPLETION_LOG_STATUS_CACHE = None
    assert m._completion_log_status_map(repo_root).get("044") == "complete"
    assert (
        m._consumer_status_for_artifact(repo_root, "044-prd-issue-store-migration", "prd")
        == "complete"
    )


def test_brainstorm_status_complete(repo_root: Path) -> None:
    import planning_migrate_issue_store as m

    assert (
        m._consumer_status_for_artifact(
            repo_root,
            "brainstorm-2026-06-24-native-local-review-panel-requirements",
            "brainstorm",
            body_path="docs/brainstorms/2026-06-24-native-local-review-panel-requirements.md",
        )
        == "complete"
    )


def test_frontmatter_status_for_closed_brainstorm() -> None:
    lifecycle = ArtifactLifecycle(
        issue_state="closed",
        frozen=False,
        freeze_hash=None,
        frozen_at=None,
        consumer_status="complete",
    )
    assert _frontmatter_status_for_lifecycle(lifecycle, "brainstorm") == "complete"


def test_render_file_with_lifecycle_round_trip_issue_state() -> None:
    for artifact_type, issue_state, consumer_status in (
        ("brainstorm", "closed", "complete"),
        ("prd", "closed", "complete"),
        ("prd", "open", "not-started"),
        ("gap", "closed", None),
    ):
        lifecycle = ArtifactLifecycle(
            issue_state=issue_state,
            frozen=True,
            freeze_hash=None,
            frozen_at="2026-06-24",
            gap_status="resolved" if artifact_type == "gap" else None,
            consumer_status=consumer_status,
        )
        rendered = render_file_with_lifecycle(
            "# Body\n",
            lifecycle,
            f"unit-{artifact_type}",
            artifact_type,
        )
        got = extract_lifecycle_from_file(rendered, artifact_type)
        expected = ArtifactLifecycle(
            issue_state=issue_state,
            frozen=True,
            freeze_hash=None,
            frozen_at="2026-06-24",
            gap_status=lifecycle.gap_status,
            consumer_status=consumer_status,
        )
        assert lifecycle_equal(expected, got), (artifact_type, issue_state, got)


def test_issues_client_mark_tombstone_fixture(tmp_path: Path, monkeypatch) -> None:
    import os
    from issues_lib import IssuesClient, IssueNotFound

    monkeypatch.setenv("SW_ISSUES_FIXTURE", "1")
    root = tmp_path
    (root / ".cursor" / "hooks" / "state").mkdir(parents=True)
    client = IssuesClient(root, "jira")
    record = client.issue_create(
        title="[shipwright] gap:gap-test",
        body="<!-- sw-unit-id: gap-test -->\nbody",
        labels=["sw:project:shipwright", "sw:gap"],
        project_key="shipwright",
        artifact_type="gap",
        unit_id="gap-test",
    )
    client.mark_tombstone(record.id)
    try:
        client.issue_get(record.id)
        raise AssertionError("expected tombstone")
    except IssueNotFound:
        pass


def test_jira_mark_tombstone_delete(monkeypatch, tmp_path: Path) -> None:
    from io import BytesIO
    from unittest.mock import MagicMock
    from urllib.error import HTTPError

    import planning_jira_client as jc

    calls: list[str] = []

    def fake_urlopen(req, timeout=30):
        calls.append(req.method + " " + req.full_url)
        if req.method == "DELETE":
            return MagicMock(status=204, headers={}, read=lambda: b"", __enter__=lambda s: s, __exit__=lambda *a: None)
        raise AssertionError(f"unexpected request: {req.method} {req.full_url}")

    import issues_http

    monkeypatch.setattr(issues_http, "_urlopen", fake_urlopen)
    monkeypatch.setenv("ISSUES_JIRA_TOKEN", "token")
    monkeypatch.setenv("ISSUES_JIRA_EMAIL", "user@example.com")

    cfg = {
        "planning": {
            "store": {
                "projectKey": "shipwright",
                "issues": {"endpoint": "https://example.atlassian.net", "flavor": "cloud"},
            }
        }
    }
    monkeypatch.setattr(jc, "load_workflow_config", lambda _root: cfg)
    monkeypatch.setattr(jc, "resolve_jira_flavor", lambda _cfg: "cloud")
    monkeypatch.setattr(jc, "resolve_jira_endpoint", lambda _cfg: "https://example.atlassian.net")
    monkeypatch.setattr(jc, "resolve_jira_project_key", lambda _cfg: "shipwright")
    monkeypatch.setattr(jc, "resolve_jira_api_project_key", lambda _cfg, _token, _root=None: "SHIPWRIGHT")
    monkeypatch.setattr(jc, "resolve_jira_issue_type", lambda _cfg: "Task")
    monkeypatch.setattr(jc, "resolve_field_defaults", lambda _cfg: {})

    client = jc.JiraIssuesClient(tmp_path)
    client.mark_tombstone("SHIPWRIGHT-99")
    assert any("DELETE" in c and "SHIPWRIGHT-99" in c for c in calls)


def test_github_mark_tombstone_degraded(monkeypatch, tmp_path: Path) -> None:
    import json
    from unittest.mock import MagicMock

    import planning_github_client as gc

    calls: list[tuple[str, str, dict | list | None]] = []

    def fake_urlopen(req, timeout=30):
        method = req.method
        url = req.full_url
        payload = None
        if req.data:
            payload = __import__("json").loads(req.data.decode("utf-8"))
        calls.append((method, url, payload))
        if method == "GET" and "/issues/42" in url and "/comments" not in url:
            body = json.dumps(
                {
                    "number": 42,
                    "title": "t",
                    "body": "<!-- sw-unit-id: u1 -->\nbody",
                    "state": "open",
                    "labels": [{"name": "sw:project:shipwright-planning"}],
                    "updated_at": "2026-01-01T00:00:00Z",
                    "locked": False,
                }
            )
            return MagicMock(status=200, headers={}, read=lambda: body.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)
        if method == "GET" and "/issues/42/comments" in url:
            return MagicMock(status=200, headers={}, read=lambda: b"[]", __enter__=lambda s: s, __exit__=lambda *a: None)
        if method == "PATCH" and "/issues/42" in url and "/labels" not in url:
            return MagicMock(status=200, headers={}, read=lambda: b"{}", __enter__=lambda s: s, __exit__=lambda *a: None)
        if method == "POST" and "/issues/42/labels" in url:
            return MagicMock(status=200, headers={}, read=lambda: b"[]", __enter__=lambda s: s, __exit__=lambda *a: None)
        if method == "POST" and "/issues/42/comments" in url:
            return MagicMock(
                status=200,
                headers={},
                read=lambda: b'{"id":1,"body":"x","created_at":"2026-01-01T00:00:00Z"}',
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        raise AssertionError(f"unexpected request: {method} {url}")

    import issues_http

    monkeypatch.setattr(issues_http, "_urlopen", fake_urlopen)
    monkeypatch.setenv("ISSUES_GITHUB_TOKEN", "token")
    cfg = {
        "planning": {
            "store": {
                "projectKey": "shipwright-planning",
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "grdavies",
                    "repo": "shipwright-planning",
                },
                "issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"},
            }
        },
        "host": {"provider": "github"},
    }
    monkeypatch.setattr(gc, "load_workflow_config", lambda _root: cfg)

    client = gc.GitHubIssuesClient(tmp_path)
    client.mark_tombstone("42")
    patch_calls = [c for c in calls if c[0] == "PATCH"]
    comment_calls = [c for c in calls if c[0] == "POST" and "/comments" in c[1]]
    assert patch_calls, "expected PATCH to close/label issue"
    assert comment_calls, "expected tombstone comment"
    assert patch_calls[0][2] and patch_calls[0][2].get("state") == "closed"

def test_github_fine_grained_scope_probe(monkeypatch, tmp_path: Path) -> None:
    import json
    from unittest.mock import MagicMock

    import planning_store as ps

    calls: list[str] = []

    def fake_urlopen(req, timeout=15):
        calls.append(req.full_url)
        if req.full_url.endswith("/user"):
            return MagicMock(
                status=200,
                headers={"X-OAuth-Scopes": ""},
                read=lambda: b"{}",
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if "/repos/grdavies/shipwright-planning/issues" in req.full_url:
            body = json.dumps([])
            return MagicMock(
                status=200,
                read=lambda: body.encode(),
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        if req.full_url.endswith("/repos/grdavies/shipwright-planning"):
            body = json.dumps({"full_name": "grdavies/shipwright-planning"})
            return MagicMock(
                status=200,
                read=lambda: body.encode(),
                __enter__=lambda s: s,
                __exit__=lambda *a: None,
            )
        raise AssertionError(req.full_url)

    import issues_http

    monkeypatch.setattr(issues_http, "_urlopen", fake_urlopen)
    cfg = {
        "planning": {
            "store": {
                "projectKey": "shipwright-planning",
                "issuesProvider": "github-issues",
                "storeLocation": {
                    "mode": "separate-project",
                    "owner": "grdavies",
                    "repo": "shipwright-planning",
                },
            }
        },
        "host": {"provider": "github"},
    }
    out = ps._github_scope_probe("token", cfg, tmp_path)
    assert out["verdict"] == "ok"
    assert out.get("tokenKind") == "fine-grained"
    assert out.get("probeRepo") == "grdavies/shipwright-planning"

def test_expected_issue_verify_content_github() -> None:
    from planning_canonical import normalize_body
    from planning_migrate_issue_store import _expected_issue_verify_content
    from planning_jira_canonical import jira_markdown_canonical

    body = "## Title\n\n- bullet\n"
    assert _expected_issue_verify_content(body, "github-issues") == normalize_body(body)
    assert _expected_issue_verify_content(body, "jira") == jira_markdown_canonical(body)


def test_expected_verify_lifecycle_uses_index_consumer_status(repo_root: Path) -> None:
    from planning_migrate_issue_store import (
        MigrationArtifact,
        _expected_verify_lifecycle,
        _file_body_content,
        extract_lifecycle_from_file,
    )

    fixture = (
        repo_root
        / "scripts/test/fixtures/planning-post-migration/039-loop-quality-gates/039-prd-loop-quality-gates.md"
    )
    raw = fixture.read_text(encoding="utf-8")
    lifecycle = extract_lifecycle_from_file(raw, "prd")
    artifact = MigrationArtifact(
        source_path="scripts/test/fixtures/planning-post-migration/039-loop-quality-gates/039-prd-loop-quality-gates.md",
        body_path="scripts/test/fixtures/planning-post-migration/039-loop-quality-gates/039-prd-loop-quality-gates.md",
        unit_id="039-prd-loop-quality-gates",
        content=_file_body_content(raw),
        digest="x",
        artifact_type="prd",
        lifecycle=lifecycle,
    )
    expected = _expected_verify_lifecycle(repo_root, artifact, {}, "test", freeze_hash=None)
    assert expected.consumer_status == "complete"
    assert expected.issue_state == "closed"

@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
def test_github_search_rate_limit_retries(monkeypatch, tmp_path: Path) -> None:
    import json
    from unittest.mock import MagicMock

    import issues_http
    from host_ratelimit import execute_with_retry, RequestResult

    attempts = {"n": 0}

    def fake_urlopen(req, timeout=30):
        attempts["n"] += 1
        if attempts["n"] == 1:
            from urllib.error import HTTPError
            raise HTTPError(
                req.full_url,
                403,
                "Forbidden",
                {
                    "x-ratelimit-resource": "search",
                    "x-ratelimit-remaining": "0",
                    "retry-after": "0",
                },
                __import__("io").BytesIO(b'{"message":"API rate limit exceeded"}'),
            )
        body = json.dumps({"items": []})
        return MagicMock(status=200, headers={}, read=lambda: body.encode(), __enter__=lambda s: s, __exit__=lambda *a: None)

    monkeypatch.setattr(issues_http, "_urlopen", fake_urlopen)

    cfg = {
        "planning": {"store": {"issues": {"tokenEnv": "ISSUES_GITHUB_TOKEN"}}},
        "host": {"provider": "github", "rateLimit": {"maxAttempts": 3, "baseBackoffMs": 1, "capBackoffMs": 5, "maxCumulativeWaitMs": 5000, "jitter": False}},
    }

    import planning_github_client as gc

    monkeypatch.setattr(gc, "load_workflow_config", lambda _root: cfg)
    monkeypatch.setenv("ISSUES_GITHUB_TOKEN", "token")
    monkeypatch.setattr(gc, "_resolve_repo_target", lambda _r, _c: ("grdavies", "planning"))

    client = gc.GitHubIssuesClient(tmp_path)
    results = client.search(project_key="planning")
    assert results == []
    assert attempts["n"] >= 2


def test_is_throttled_github_search_body_hint() -> None:
    from host_ratelimit import is_throttled

    assert is_throttled(
        403,
        {"x-ratelimit-remaining": "10"},
        "github",
        body='{"message":"API rate limit exceeded"}',
    )
    assert not is_throttled(403, {"x-ratelimit-remaining": "10"}, "github", body="Forbidden")

