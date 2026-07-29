"""PRD 082 phase 25 — cross-project trusted-source authorization fixtures (R32)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2]
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import planning_cross_project_recall as recall  # noqa: E402
import planning_cross_project_trust as trust  # noqa: E402


def _write_cfg(repo: Path, cfg: dict) -> None:
    path = repo / ".cursor" / "workflow.config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def _base_cfg(*, project_key: str = "proj-b", trusted: list[str] | None = None) -> dict:
    return {
        "planning": {
            "store": {
                "backend": "issue-store",
                "issuesProvider": "github-issues",
                "projectKey": project_key,
            }
        },
        "memory": {
            "crossProjectTrustedSources": trusted or ["proj-a", "proj-c"],
        },
        "host": {"provider": "github"},
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    _write_cfg(tmp_path, _base_cfg())
    return tmp_path


class TestTrustedSourceResolver:
    def test_reads_trusted_set_from_worktree_config(self, repo: Path) -> None:
        result = trust.resolve_trusted_sources(repo)
        assert result["verdict"] == "pass"
        assert result["callerProjectKey"] == "proj-b"
        assert result["configuredTrustedSources"] == ["proj-a", "proj-c"]

    def test_payload_widening_rejected(self, repo: Path) -> None:
        result = trust.resolve_trusted_sources(
            repo,
            payload_authorized_projects=["proj-a", "proj-z"],
        )
        assert result["verdict"] == "fail"
        assert result["error"] == "payload-widening-rejected"

    def test_payload_narrowing_ignored_outside_harness(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SW_HARNESS", raising=False)
        result = trust.resolve_trusted_sources(
            repo,
            payload_authorized_projects=["proj-a"],
            allow_payload_trust=True,
        )
        assert result["verdict"] == "pass"
        assert result["effectiveTrustedSources"] == ["proj-a", "proj-c"]
        assert result["payloadTrustApplied"] is False

    def test_payload_narrowing_honoured_in_harness(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SW_HARNESS", "1")
        result = trust.resolve_trusted_sources(
            repo,
            payload_authorized_projects=["proj-a"],
            allow_payload_trust=True,
        )
        assert result["verdict"] == "pass"
        assert result["effectiveTrustedSources"] == ["proj-a"]
        assert result["payloadTrustApplied"] is True

    def test_test_only_flag_inert_outside_harness(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SW_HARNESS", raising=False)
        assert trust.harness_allows_payload_trust() is False
        result = trust.resolve_trusted_sources(
            repo,
            payload_authorized_projects=["proj-a"],
            allow_payload_trust=True,
        )
        assert result["payloadTrustApplied"] is False


class TestCrossProjectRecallAuthorization:
    def test_authorization_from_config_not_payload_caller(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(recall, "redact_text", lambda text: text)
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-a",
            caller_project_key="proj-attacker",
            query="",
            pointers=[
                {
                    "projectKey": "proj-a",
                    "unitId": "u1",
                    "memoryId": "m1",
                    "visibility": "public",
                    "excerpt": "shared rationale",
                }
            ],
            authorized_projects=["proj-a"],
        )
        assert result["verdict"] == "denied"
        assert result["error"] == "caller-project-key-mismatch"

    def test_unauthorized_source_denied(self, repo: Path) -> None:
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-z",
            query="",
            pointers=[],
        )
        assert result["verdict"] == "denied"
        assert result["error"] == "cross-project-unauthorized"

    def test_payload_widening_rejected_on_recall(self, repo: Path) -> None:
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-z",
            query="",
            pointers=[],
            authorized_projects=["proj-z"],
        )
        assert result["verdict"] == "fail"
        assert result["error"] == "payload-widening-rejected"

    def test_secret_record_never_crosses_project_boundary(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(recall, "redact_text", lambda text: text)
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-a",
            query="",
            pointers=[
                {
                    "projectKey": "proj-a",
                    "unitId": "secret-unit",
                    "memoryId": "m-secret",
                    "visibility": "public",
                    "sensitivity": "secret",
                    "excerpt": "must not cross",
                }
            ],
            authorized_projects=["proj-a"],
        )
        assert result["verdict"] == "pass"
        assert result["hits"] == []

    def test_personal_record_never_crosses_project_boundary(self, repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(recall, "redact_text", lambda text: text)
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-a",
            query="",
            pointers=[
                {
                    "projectKey": "proj-a",
                    "unitId": "personal-unit",
                    "memoryId": "m-personal",
                    "visibility": "public",
                    "category": "personal",
                    "excerpt": "must not cross",
                }
            ],
            authorized_projects=["proj-a"],
        )
        assert result["verdict"] == "pass"
        assert result["hits"] == []

    def test_private_visibility_still_opaque_cross_project(self, repo: Path) -> None:
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-a",
            query="",
            pointers=[
                {
                    "projectKey": "proj-a",
                    "unitId": "u-private",
                    "memoryId": "m-private",
                    "visibility": "private",
                    "excerpt": "Secret rationale text",
                }
            ],
            authorized_projects=["proj-a"],
        )
        assert result["verdict"] == "pass"
        assert len(result["hits"]) == 1
        assert result["hits"][0]["excerpt"] == "u-private: [private]"
        assert "Secret rationale" not in result["hits"][0]["excerpt"]

    def test_same_project_private_still_opaque(self, repo: Path) -> None:
        _write_cfg(repo, _base_cfg(project_key="proj-a", trusted=["proj-b"]))
        result = recall.recall_cross_project(
            repo,
            source_project_key="proj-a",
            query="",
            pointers=[
                {
                    "projectKey": "proj-a",
                    "unitId": "u-private",
                    "memoryId": "m-private",
                    "visibility": "private",
                    "excerpt": "Secret rationale text",
                }
            ],
        )
        assert result["verdict"] == "pass"
        assert len(result["hits"]) == 1
        assert result["hits"][0]["excerpt"] == "u-private: [private]"
